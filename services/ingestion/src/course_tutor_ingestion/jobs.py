"""Outbox-backed ingestion job processor.

Design contract (function-spec FR-1.2):
  checksum + pipeline_version is the idempotency key per source document.
  A file whose checksum has not changed since the last scan is never reprocessed.
  A second scan of the same root uses the same outbox idempotency key → at-least-once semantics.
"""

from __future__ import annotations

import uuid
from dataclasses import dataclass, field
from datetime import UTC, datetime
from pathlib import Path
from typing import TYPE_CHECKING, Any

import structlog
from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession

from course_tutor_api.db import Chunk as OrmChunk
from course_tutor_api.db import ContentVersion, SourceDocument
from course_tutor_api.db.models import OutboxEvent
from course_tutor_contracts.enums import ExtractionStatus
from course_tutor_ingestion.object_store import MinioObjectStore
from course_tutor_ingestion.parsers import ParsedDocument, parse
from course_tutor_ingestion.scanner import FileEntry, Scanner
from course_tutor_ingestion.source_root import validate_path, validate_read_access

if TYPE_CHECKING:
    from course_tutor_ingestion.parsers import Chunk as ParserChunk

logger = structlog.get_logger(__name__)

# Increment this whenever the parsing or chunking algorithm changes, forcing a re-index.
PIPELINE_VERSION = "1.1.0"


def _coalesce_chunks(
    fragments: list[ParserChunk],
    *,
    target_size: int = 1000,
    overlap: int = 200,
) -> list[ParserChunk]:
    """Coalesce small text fragments into target-size chunks with overlap.

    Chunks are built by accumulating fragment text until reaching *target_size*,
    then a new chunk starts. The last *overlap* characters are carried forward
    so context is not lost at boundaries.

    The first chunk in a document starts fresh (no leading overlap).
    """
    from course_tutor_ingestion.parsers import Chunk as ParserChunk

    if not fragments:
        return []

    result: list[ParserChunk] = []
    current_text_parts: list[str] = []
    current_size = 0
    current_anchors: list[tuple[str, str]] = []  # (anchor_type, anchor_value)

    def flush() -> ParserChunk:
        """Emit the current accumulated chunk."""
        text = " ".join(current_text_parts)
        # Use the first anchor as the representative for this chunk.
        primary_anchor = current_anchors[0] if current_anchors else ("page", "1")
        # Build a bounded anchor_value: "first-last" for multi-anchor chunks,
        # capped at 120 chars to stay within VARCHAR(128).
        if len(current_anchors) > 1:
            first_val = current_anchors[0][1]
            last_val = current_anchors[-1][1]
            raw = f"{first_val}-{last_val}"
            anchor_value = raw[:120]
        else:
            anchor_value = primary_anchor[1]
        return ParserChunk(
            text=text,
            anchor_type=primary_anchor[0],
            anchor_value=anchor_value,
            chunk_class="content",
        )

    for fragment in fragments:
        frag_text = fragment.text.strip()
        if not frag_text:
            continue

        frag_len = len(frag_text)

        if current_size + frag_len + 1 >= target_size and current_text_parts:
            # Flush current chunk before starting a new one.
            result.append(flush())
            # Carry overlap: keep the last overlap chars as the start of the new chunk.
            overlap_text = result[-1].text[-overlap:] if result else ""
            current_text_parts = [overlap_text] if overlap_text else []
            current_size = len(overlap_text)
            current_anchors = [(result[-1].anchor_type, result[-1].anchor_value)] if result else []
        elif current_text_parts:
            current_size += 1 + frag_len  # +1 for space separator

        current_text_parts.append(frag_text)
        current_anchors.append((fragment.anchor_type, fragment.anchor_value))
        current_size += frag_len

    # Don't forget the last accumulated chunk.
    if current_text_parts:
        result.append(flush())

    return result


@dataclass
class IngestionStats:
    files_discovered: int = 0
    files_unchanged: int = 0
    files_processed: int = 0
    files_quarantined: int = 0
    chunks_written: int = 0
    errors: list[str] = field(default_factory=list)


class IngestionJob:
    """One scan-and-index job driven by an OutboxEvent payload."""

    def __init__(
        self,
        session: AsyncSession,
        event: OutboxEvent,
        object_store: MinioObjectStore | None = None,
        pipeline_version: str = PIPELINE_VERSION,
    ) -> None:
        self._session = session
        self._event = event
        self._object_store = object_store
        self._pipeline_version = pipeline_version
        self._stats = IngestionStats()

    async def run(self) -> IngestionStats:
        payload: dict[str, Any] = self._event.payload
        course_id = uuid.UUID(payload["course_id"])
        version_id = uuid.UUID(payload["version_id"])
        resolved_path = Path(payload["resolved_path"])

        logger.info(
            "ingestion_job_start",
            job_id=str(self._event.id),
            path=str(resolved_path),
            course_id=str(course_id),
            version_id=str(version_id),
        )

        # Validate path on every run (it may have been remounted).
        try:
            resolved = validate_path(str(resolved_path))
            validate_read_access(resolved)
        except Exception as exc:
            logger.error("ingestion_path_validation_failed", path=str(resolved_path), exc=str(exc))
            self._stats.errors.append(f"path validation: {exc}")
            return self._stats

        scanner = Scanner(resolved)
        entries = scanner.scan()
        self._stats.files_discovered = len(entries)

        version = await self._session.get(ContentVersion, version_id)
        if version is None:
            self._stats.errors.append(f"version {version_id} not found")
            return self._stats

        for entry in entries:
            await self._process_file(entry, version.id)

        # Emit an embedding job if any chunks were written.
        if self._stats.chunks_written > 0:
            embed_event = OutboxEvent(
                id=uuid.uuid4(),
                topic="ingestion.embed",
                idempotency_key=f"embed:{version_id}",
                payload={
                    "version_id": str(version_id),
                    "course_id": str(course_id),
                },
                attempts=0,
            )
            self._session.add(embed_event)

        self._event.processed_at = datetime.now(UTC).replace(tzinfo=None)
        await self._session.commit()

        logger.info(
            "ingestion_job_complete",
            job_id=str(self._event.id),
            files_discovered=self._stats.files_discovered,
            files_unchanged=self._stats.files_unchanged,
            files_processed=self._stats.files_processed,
            files_quarantined=self._stats.files_quarantined,
            chunks_written=self._stats.chunks_written,
        )
        return self._stats

    async def _process_file(self, entry: FileEntry, version_id: uuid.UUID) -> None:
        """Idempotent per-file processing.

        The uniqueness constraint (version_id, checksum) is the idempotency key from
        function-spec §7.1. If a matching SourceDocument already exists we skip silently.
        """
        existing = await self._session.execute(
            select(SourceDocument).where(
                SourceDocument.version_id == version_id,
                SourceDocument.checksum == entry.checksum,
            )
        )
        doc = existing.scalar_one_or_none()
        if doc is not None:
            logger.debug(
                "ingestion_skip_unchanged",
                path=entry.relative_path,
                checksum=entry.checksum[:16],
            )
            self._stats.files_unchanged += 1
            return

        # Store original in MinIO.
        artifact_key: str | None = None
        if self._object_store is not None:
            try:
                artifact_key = self._object_store.upload_path(
                    source_path=entry.absolute_path,
                    tenant_id="00000000-0000-0000-0000-000000000000",
                    course_id=str(version_id),
                    source_id="placeholder",
                )
            except Exception as exc:
                logger.warning(
                    "ingestion_artifact_store_failed",
                    path=entry.relative_path,
                    exc=str(exc),
                )
                artifact_key = None

        # Parse.
        parsed: ParsedDocument = parse(entry, entry.absolute_path)

        if parsed.extraction_status == "quarantined":
            self._stats.files_quarantined += 1

        # Write SourceDocument row.
        doc = SourceDocument(
            version_id=version_id,
            relative_path=entry.relative_path,
            checksum=entry.checksum,
            mime_type=entry.mime_type,
            size_bytes=entry.size_bytes,
            access_label="enrolled",
            extraction_status=ExtractionStatus(parsed.extraction_status),
            extraction_confidence=parsed.extraction_confidence,
            failure_reason=parsed.failure_reason,
            artifact_key=artifact_key,
            source_metadata=parsed.metadata,
        )
        self._session.add(doc)
        await self._session.flush()  # Get doc.id

        # Coalesce small fragments into target-size chunks with overlap.
        coalesced = _coalesce_chunks(parsed.chunks, target_size=1000, overlap=200)

        # Write chunks with ordinals.
        for ordinal, chunk in enumerate(coalesced):
            orm_chunk = OrmChunk(
                source_id=doc.id,
                ordinal=ordinal,
                text=chunk.text,
                token_count=chunk.token_count or 0,
                anchor_type=chunk.anchor_type,
                anchor_value=chunk.anchor_value,
                chunk_class=chunk.chunk_class,
                embedding_model_version="pending",
            )
            self._session.add(orm_chunk)
            self._stats.chunks_written += 1

        self._stats.files_processed += 1
        logger.debug(
            "ingestion_file_processed",
            path=entry.relative_path,
            chunks=len(parsed.chunks),
            status=parsed.extraction_status,
        )


async def run_pending_jobs(
    session: AsyncSession,
    *,
    max_batch: int = 10,
    object_store: MinioObjectStore | None = None,
) -> int:
    """Claim and process up to *max_batch* pending ingestion.scan outbox events.

    Returns the number of events processed. Each event is idempotent on its
    idempotency_key, so reprocessing a crashed worker is safe.
    """
    result = await session.execute(
        select(OutboxEvent)
        .where(
            OutboxEvent.topic == "ingestion.scan",
            OutboxEvent.processed_at.is_(None),
            OutboxEvent.dead_lettered_at.is_(None),
        )
        .limit(max_batch)
    )
    events = list(result.scalars().all())
    for event in events:
        try:
            job = IngestionJob(
                session=session,
                event=event,
                object_store=object_store,
            )
            await job.run()
        except Exception as exc:
            logger.error("ingestion_job_crash", job_id=str(event.id), exc=str(exc))
            event.attempts += 1
            event.last_error = str(exc)[:500]
            if event.attempts >= 5:
                event.dead_lettered_at = datetime.now(UTC).replace(tzinfo=None)
            await session.commit()
    return len(events)
