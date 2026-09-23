"""Incremental, immutable ingestion driven by a transactionally claimed outbox."""

from __future__ import annotations

import asyncio
import hashlib
import re
import uuid
from dataclasses import asdict, dataclass, field
from datetime import UTC, datetime
from typing import TYPE_CHECKING

import structlog
from sqlalchemy import func, select
from sqlalchemy.ext.asyncio import AsyncSession

from course_tutor_api.db import Chunk as OrmChunk
from course_tutor_api.db import (
    ContentVersion,
    ContentVersionSource,
    Course,
    CourseRun,
    OutboxEvent,
    SourceDocument,
    SourceRoot,
)
from course_tutor_contracts.enums import AccessLabel, ContentVersionStatus, ExtractionStatus
from course_tutor_ingestion.object_store import MinioObjectStore
from course_tutor_ingestion.parsers import ParsedDocument, parse
from course_tutor_ingestion.scanner import FileEntry, Scanner
from course_tutor_ingestion.source_root import validate_path, validate_read_access
from course_tutor_shared import INGESTION_JOBS, PIPELINE_VERSION, correlation_id_var

if TYPE_CHECKING:
    from course_tutor_ingestion.parsers import Chunk as ParserChunk

logger = structlog.get_logger(__name__)


def snapshot_hash(entries: list[FileEntry]) -> str:
    """Hash path + content checksum so add/change/delete/rename are all observable."""
    digest = hashlib.sha256()
    for entry in sorted(entries, key=lambda item: item.relative_path):
        digest.update(entry.relative_path.encode())
        digest.update(b"\0")
        digest.update(entry.checksum.encode())
        digest.update(b"\n")
    return digest.hexdigest()


def approximate_token_count(text: str) -> int:
    """Stable fallback token count for local models without a tokenizer endpoint."""
    return len(re.findall(r"\w+|[^\s\w]", text, flags=re.UNICODE))


def _coalesce_chunks(
    fragments: list[ParserChunk], *, target_size: int = 1000, overlap: int = 200
) -> list[ParserChunk]:
    """Coalesce only fragments with the same semantic class and anchor type."""
    from course_tutor_ingestion.parsers import Chunk as ParserChunk

    result: list[ParserChunk] = []
    parts: list[str] = []
    anchors: list[str] = []
    active_type: str | None = None
    active_class: str | None = None

    def flush() -> None:
        if not parts or active_type is None or active_class is None:
            return
        text = " ".join(parts).strip()
        unique_anchors = list(dict.fromkeys(anchors))
        anchor = (
            unique_anchors[0]
            if len(unique_anchors) == 1
            else f"{unique_anchors[0]}-{unique_anchors[-1]}"[:120]
        )
        result.append(
            ParserChunk(
                text=text,
                anchor_type=active_type,
                anchor_value=anchor,
                chunk_class=active_class,
                token_count=approximate_token_count(text),
            )
        )

    for fragment in fragments:
        text = fragment.text.strip()
        if not text:
            continue
        preserve_visual_boundary = (
            active_type in {"page", "slide"} and fragment.anchor_value != anchors[-1]
        )
        boundary = active_type is not None and (
            fragment.anchor_type != active_type
            or fragment.chunk_class != active_class
            or preserve_visual_boundary
        )
        oversized = parts and len(" ".join(parts)) + len(text) + 1 > target_size
        if boundary or oversized:
            flush()
            carry = result[-1].text[-overlap:] if oversized and not boundary and result else ""
            parts = [carry] if carry else []
            anchors = [result[-1].anchor_value] if carry else []
        active_type = fragment.anchor_type
        active_class = fragment.chunk_class
        parts.append(text)
        anchors.append(fragment.anchor_value)
    flush()
    return result


@dataclass
class IngestionStats:
    files_discovered: int = 0
    files_unchanged: int = 0
    files_processed: int = 0
    files_reused: int = 0
    files_quarantined: int = 0
    chunks_written: int = 0
    no_change: bool = False
    errors: list[str] = field(default_factory=list)


class IngestionJob:
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
        if self._event.processed_at is not None:
            self._stats.no_change = True
            return self._stats
        payload = dict(self._event.payload)
        course_id = uuid.UUID(payload["course_id"])
        course = await self._session.get(Course, course_id)
        if course is None:
            raise ValueError(f"course {course_id} not found")
        if payload.get("tenant_id") and payload["tenant_id"] != str(course.tenant_id):
            raise ValueError("ingestion tenant does not own course")

        source_root = (
            await self._session.get(SourceRoot, uuid.UUID(payload["source_root_id"]))
            if payload.get("source_root_id")
            else await self._session.get(SourceRoot, course.source_root_id)
            if course.source_root_id
            else None
        )
        if source_root is None or source_root.tenant_id != course.tenant_id:
            raise ValueError("course source root is missing or crosses tenant boundary")
        if raw_run := payload.get("course_run_id"):
            course_run = await self._session.get(CourseRun, uuid.UUID(raw_run))
        else:
            run_result = await self._session.execute(
                select(CourseRun)
                .where(
                    CourseRun.course_id == course.id,
                    CourseRun.source_root_id == source_root.id,
                )
                .order_by(CourseRun.created_at.desc())
                .limit(1)
            )
            course_run = run_result.scalar_one_or_none()
        if course_run is None or course_run.course_id != course.id:
            raise ValueError("course run is missing or does not own source root")

        resolved = validate_path(payload.get("resolved_path", source_root.absolute_path))
        validate_read_access(resolved)
        entries = Scanner(resolved).scan()
        self._stats.files_discovered = len(entries)
        current_snapshot = snapshot_hash(entries)

        # New API events create a version only after change detection. Old queued
        # events that already contain version_id remain consumable during rollout.
        version = None
        unchanged_version_exists = False
        if raw_version := payload.get("version_id"):
            version = await self._session.get(ContentVersion, uuid.UUID(raw_version))
            if version is None or version.course_id != course.id:
                raise ValueError("queued content version is invalid")
        else:
            baseline_result = await self._session.execute(
                select(ContentVersion.id).where(
                    ContentVersion.course_id == course.id,
                    ContentVersion.course_run_id == course_run.id,
                    ContentVersion.pipeline_version == self._pipeline_version,
                    ContentVersion.source_snapshot_hash == current_snapshot,
                    ContentVersion.status.in_(
                        [
                            ContentVersionStatus.BUILDING,
                            ContentVersionStatus.READY,
                            ContentVersionStatus.PUBLISHED,
                        ]
                    ),
                )
            )
            unchanged_version_exists = baseline_result.first() is not None

        if version is None and unchanged_version_exists:
            self._stats.no_change = True
            self._stats.files_unchanged = len(entries)
            source_root.last_scanned_at = datetime.now(UTC).replace(tzinfo=None)
            payload["stats"] = asdict(self._stats)
            self._event.payload = payload
            self._event.processed_at = datetime.now(UTC).replace(tzinfo=None)
            await self._session.commit()
            return self._stats
        elif version is None:
            sequence_result = await self._session.execute(
                select(func.coalesce(func.max(ContentVersion.sequence), 0)).where(
                    ContentVersion.course_run_id == course_run.id
                )
            )
            version = ContentVersion(
                id=uuid.uuid4(),
                course_id=course.id,
                course_run_id=course_run.id,
                pipeline_version=self._pipeline_version,
                sequence=int(sequence_result.scalar_one()) + 1,
                status=ContentVersionStatus.BUILDING,
                embedding_model_version="pending",
                embedding_dimension=int(payload.get("embedding_dimension", 1024)),
                source_snapshot_hash=current_snapshot,
            )
            self._session.add(version)
            payload["version_id"] = str(version.id)

        assert version is not None
        for entry in entries:
            await self._process_file(entry, version, course)

        self._session.add(
            OutboxEvent(
                id=uuid.uuid4(),
                topic="ingestion.embed",
                idempotency_key=f"embed:{version.id}",
                payload={
                    "tenant_id": str(course.tenant_id),
                    "course_id": str(course.id),
                    "course_run_id": str(course_run.id),
                    "version_id": str(version.id),
                },
                attempts=0,
            )
        )
        source_root.last_snapshot_hash = current_snapshot
        source_root.last_scanned_at = datetime.now(UTC).replace(tzinfo=None)
        payload["stats"] = asdict(self._stats)
        self._event.payload = payload
        self._event.processed_at = datetime.now(UTC).replace(tzinfo=None)
        await self._session.commit()
        return self._stats

    async def _process_file(
        self, entry: FileEntry, version: ContentVersion, course: Course
    ) -> None:
        result = await self._session.execute(
            select(SourceDocument)
            .join(ContentVersion, SourceDocument.version_id == ContentVersion.id)
            .where(
                ContentVersion.course_id == course.id,
                ContentVersion.pipeline_version == self._pipeline_version,
                SourceDocument.relative_path == entry.relative_path,
                SourceDocument.checksum == entry.checksum,
            )
            .order_by(SourceDocument.created_at.desc())
            .limit(1)
        )
        reusable = result.scalar_one_or_none()
        if reusable is not None:
            self._session.add(ContentVersionSource(version_id=version.id, source_id=reusable.id))
            self._stats.files_reused += 1
            return

        parsed: ParsedDocument = parse(entry, entry.absolute_path)
        if parsed.extraction_status == ExtractionStatus.QUARANTINED.value:
            self._stats.files_quarantined += 1
        doc = SourceDocument(
            id=uuid.uuid4(),
            version_id=version.id,
            relative_path=entry.relative_path,
            checksum=entry.checksum,
            mime_type=entry.mime_type,
            size_bytes=entry.size_bytes,
            access_label=AccessLabel.ENROLLED,
            extraction_status=ExtractionStatus(parsed.extraction_status),
            extraction_confidence=parsed.extraction_confidence,
            failure_reason=parsed.failure_reason,
            artifact_key=None,
            source_metadata=parsed.metadata,
        )
        self._session.add(doc)
        await self._session.flush()
        self._session.add(ContentVersionSource(version_id=version.id, source_id=doc.id))

        if self._object_store is not None:
            try:
                doc.artifact_key = await asyncio.to_thread(
                    self._object_store.upload_path,
                    entry.absolute_path,
                    entry.checksum,
                )
            except Exception as exc:
                logger.warning(
                    "ingestion_artifact_store_failed",
                    path=entry.relative_path,
                    exc=str(exc),
                )

        chunks = _coalesce_chunks(parsed.chunks)
        for ordinal, chunk in enumerate(chunks):
            self._session.add(
                OrmChunk(
                    source_id=doc.id,
                    ordinal=ordinal,
                    text=chunk.text,
                    token_count=chunk.token_count or approximate_token_count(chunk.text),
                    anchor_type=chunk.anchor_type,
                    anchor_value=chunk.anchor_value,
                    chunk_class=chunk.chunk_class,
                    embedding_model_version="pending",
                )
            )
            self._stats.chunks_written += 1
        self._stats.files_processed += 1


async def enqueue_due_scans(session: AsyncSession, now: datetime | None = None) -> int:
    """Create one periodic scan event per due course, without duplicating pending work."""
    now = now or datetime.now(UTC).replace(tzinfo=None)
    result = await session.execute(
        select(Course, SourceRoot, CourseRun)
        .join(SourceRoot, Course.source_root_id == SourceRoot.id)
        .join(
            CourseRun,
            (CourseRun.course_id == Course.id) & (CourseRun.source_root_id == SourceRoot.id),
        )
        .where(SourceRoot.automatic_ingestion_enabled.is_(True))
    )
    queued = 0
    for course, source_root, course_run in result.all():
        elapsed = (
            float("inf")
            if source_root.last_scanned_at is None
            else (now - source_root.last_scanned_at).total_seconds()
        )
        if elapsed < source_root.scan_interval_seconds:
            continue
        pending_result = await session.execute(
            select(OutboxEvent.id).where(
                OutboxEvent.topic == "ingestion.scan",
                OutboxEvent.processed_at.is_(None),
                OutboxEvent.dead_lettered_at.is_(None),
                OutboxEvent.payload["course_id"].astext == str(course.id),
            )
        )
        if pending_result.first() is not None:
            continue
        bucket = int(now.timestamp()) // source_root.scan_interval_seconds
        session.add(
            OutboxEvent(
                id=uuid.uuid4(),
                topic="ingestion.scan",
                idempotency_key=f"scan:{course.id}:scheduled:{bucket}",
                payload={
                    "tenant_id": str(course.tenant_id),
                    "course_id": str(course.id),
                    "source_root_id": str(source_root.id),
                    "course_run_id": str(course_run.id),
                    "resolved_path": source_root.absolute_path,
                    "pipeline_version": PIPELINE_VERSION,
                    "trigger": "scheduled",
                },
                attempts=0,
            )
        )
        queued += 1
    if queued:
        await session.commit()
    return queued


async def run_pending_jobs(
    session: AsyncSession,
    *,
    max_batch: int = 10,
    object_store: MinioObjectStore | None = None,
    max_attempts: int = 5,
) -> int:
    """Claim with ``FOR UPDATE SKIP LOCKED`` and process at most one lock at a time."""
    processed = 0
    for _ in range(max_batch):
        result = await session.execute(
            select(OutboxEvent)
            .where(
                OutboxEvent.topic == "ingestion.scan",
                OutboxEvent.processed_at.is_(None),
                OutboxEvent.dead_lettered_at.is_(None),
            )
            .order_by(OutboxEvent.created_at)
            .with_for_update(skip_locked=True)
            .limit(1)
        )
        event = result.scalar_one_or_none()
        if event is None:
            break
        processed += 1
        event_id = event.id
        correlation_token = correlation_id_var.set(event.correlation_id or str(event.id))
        try:
            await IngestionJob(session, event, object_store).run()
            INGESTION_JOBS.labels("ingestion-worker", "scan", "success").inc()
        except Exception as exc:
            await session.rollback()
            failed = await session.get(OutboxEvent, event_id, with_for_update=True)
            if failed is None:
                continue
            failed.attempts += 1
            failed.last_error = str(exc)[:500]
            if failed.attempts >= max_attempts:
                failed.dead_lettered_at = datetime.now(UTC).replace(tzinfo=None)
                raw_version = failed.payload.get("version_id")
                version = (
                    await session.get(ContentVersion, uuid.UUID(raw_version))
                    if raw_version
                    else None
                )
                if version is not None:
                    version.status = ContentVersionStatus.FAILED
            await session.commit()
            outcome = "dead_letter" if failed.dead_lettered_at is not None else "retry"
            INGESTION_JOBS.labels("ingestion-worker", "scan", outcome).inc()
            logger.error("ingestion_job_failed", job_id=str(event_id), exc=str(exc))
        finally:
            correlation_id_var.reset(correlation_token)
    return processed


__all__ = [
    "PIPELINE_VERSION",
    "IngestionJob",
    "IngestionStats",
    "_coalesce_chunks",
    "approximate_token_count",
    "enqueue_due_scans",
    "run_pending_jobs",
    "snapshot_hash",
]
