"""Embedding outbox job: fetches unindexed chunks and upserts vectors to Qdrant."""

from __future__ import annotations

import uuid
from dataclasses import dataclass, field
from datetime import UTC, datetime
from typing import Any

import structlog
from sqlalchemy import select, update
from sqlalchemy.ext.asyncio import AsyncSession

logger = structlog.get_logger(__name__)


@dataclass
class EmbeddingStats:
    chunks_indexed: int = 0
    versions_indexed: int = 0
    errors: list[str] = field(default_factory=list)


async def run_pending_embedding_jobs(
    session: AsyncSession,
    *,
    qdrant_client: Any,
    embed_provider: Any,
    max_batch: int = 10,
    embedding_model_version: str = "local-embedding-model",
    max_attempts: int = 5,
) -> int:
    """Claim and process up to *max_batch* pending ingestion.embed outbox events."""
    from course_tutor_retrieval.indexer import EmbeddingIndexer

    from course_tutor_api.db.models import OutboxEvent

    indexer = EmbeddingIndexer(qdrant_client=qdrant_client, embed_provider=embed_provider)
    processed = 0
    for _ in range(max_batch):
        result = await session.execute(
            select(OutboxEvent)
            .where(
                OutboxEvent.topic == "ingestion.embed",
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
        try:
            stats = await _process_embed_event(session, event, indexer, embedding_model_version)
            event.processed_at = datetime.now(UTC).replace(tzinfo=None)
            await session.commit()
            logger.info(
                "embedding_job_complete",
                job_id=str(event.id),
                chunks_indexed=stats.chunks_indexed,
            )
        except Exception as exc:
            await session.rollback()
            event = await session.get(OutboxEvent, event_id, with_for_update=True)
            if event is None:
                continue
            event.attempts += 1
            event.last_error = str(exc)[:500]
            if event.attempts >= max_attempts:
                event.dead_lettered_at = datetime.now(UTC).replace(tzinfo=None)
                raw_version = event.payload.get("version_id")
                if raw_version:
                    from course_tutor_api.db import ContentVersion
                    from course_tutor_contracts.enums import ContentVersionStatus

                    version = await session.get(ContentVersion, uuid.UUID(raw_version))
                    if version is not None:
                        version.status = ContentVersionStatus.FAILED
            await session.commit()
            logger.error("embedding_job_crash", job_id=str(event_id), exc=str(exc))

    return processed


async def _process_embed_event(
    session: AsyncSession,
    event: Any,
    indexer: Any,
    embedding_model_version: str,
) -> EmbeddingStats:
    """Process a single embedding event for one content version."""
    from course_tutor_api.db import Chunk, ContentVersion, Course, SourceDocument

    payload = event.payload
    version_id = uuid.UUID(payload["version_id"])
    course_id = uuid.UUID(payload["course_id"])

    version = await session.get(ContentVersion, version_id)
    if version is None:
        raise ValueError(f"content version {version_id} not found")

    # Fetch chunks that need embedding (no version or different version)
    result = await session.execute(
        select(Chunk)
        .join(SourceDocument)
        .where(
            SourceDocument.version_id == version_id,
            (Chunk.embedding_model_version.is_(None))
            | (Chunk.embedding_model_version == "pending")
            | (Chunk.embedding_model_version != embedding_model_version),
        )
        .order_by(Chunk.source_id, Chunk.ordinal)
    )
    chunks = list(result.scalars().all())
    if not chunks:
        logger.info("embedding_job_no_chunks", version_id=str(version_id))
        from course_tutor_contracts.enums import ContentVersionStatus

        version.status = ContentVersionStatus.READY
        version.embedding_model_version = embedding_model_version
        return EmbeddingStats(versions_indexed=1)

    # Build chunk dicts for the indexer
    chunk_dicts = []
    for chunk in chunks:
        source = await session.get(SourceDocument, chunk.source_id)
        if source is None:
            raise ValueError(f"source document {chunk.source_id} not found")
        chunk_dicts.append(
            {
                "id": chunk.id,
                "source_id": chunk.source_id,
                "ordinal": chunk.ordinal,
                "text": chunk.text,
                "anchor_type": chunk.anchor_type,
                "anchor_value": chunk.anchor_value,
                "chunk_class": chunk.chunk_class,
                "relative_path": source.relative_path,
                "mime_type": source.mime_type,
                "access_label": source.access_label,
                "token_count": chunk.token_count,
            }
        )

    # Resolve tenant_id
    course = await session.get(Course, version.course_id)
    if course is None or course.id != course_id:
        raise ValueError("embedding event course does not match content version")

    version_dict = {
        "id": version_id,
        "course_id": course_id,
        "tenant_id": course.tenant_id,
    }

    indexed = await indexer.index_chunks(chunk_dicts, version_dict)

    # Mark chunks as indexed
    chunk_ids = [c.id for c in chunks]
    await session.execute(
        update(Chunk)
        .where(Chunk.id.in_(chunk_ids))
        .values(embedding_model_version=embedding_model_version)
    )
    from course_tutor_contracts.enums import ContentVersionStatus

    version.status = ContentVersionStatus.READY
    version.embedding_model_version = embedding_model_version

    logger.info(
        "embedding_version_complete",
        version_id=str(version_id),
        chunks_indexed=indexed,
    )
    return EmbeddingStats(chunks_indexed=indexed, versions_indexed=1)
