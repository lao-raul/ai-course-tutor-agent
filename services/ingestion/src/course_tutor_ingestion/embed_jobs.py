"""Embedding outbox job: fetches unindexed chunks and upserts vectors to Qdrant."""

from __future__ import annotations

import uuid
from dataclasses import dataclass, field
from datetime import UTC, datetime
from typing import Any

import structlog
from sqlalchemy import select, update
from sqlalchemy.ext.asyncio import AsyncSession

from course_tutor_shared import INGESTION_JOBS, correlation_id_var

logger = structlog.get_logger(__name__)

CHUNK_PAGE_SIZE = 32


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
        correlation_token = correlation_id_var.set(event.correlation_id or str(event.id))
        try:
            stats = await _process_embed_event(session, event, indexer, embedding_model_version)
            event.processed_at = datetime.now(UTC).replace(tzinfo=None)
            await session.commit()
            logger.info(
                "embedding_job_complete",
                job_id=str(event.id),
                chunks_indexed=stats.chunks_indexed,
            )
            INGESTION_JOBS.labels("ingestion-worker", "embed", "success").inc()
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
            outcome = "dead_letter" if event.dead_lettered_at is not None else "retry"
            INGESTION_JOBS.labels("ingestion-worker", "embed", outcome).inc()
            logger.error("embedding_job_crash", job_id=str(event_id), exc=str(exc))
        finally:
            correlation_id_var.reset(correlation_token)

    return processed


async def _process_embed_event(
    session: AsyncSession,
    event: Any,
    indexer: Any,
    embedding_model_version: str,
) -> EmbeddingStats:
    """Process a single embedding event for one content version."""
    from course_tutor_api.db import (
        Chunk,
        ContentVersion,
        ContentVersionSource,
        Course,
        SourceDocument,
    )

    payload = event.payload
    version_id = uuid.UUID(payload["version_id"])
    course_id = uuid.UUID(payload["course_id"])

    version = await session.get(ContentVersion, version_id)
    if version is None:
        raise ValueError(f"content version {version_id} not found")

    # Resolve tenant_id
    course = await session.get(Course, version.course_id)
    if course is None or course.id != course_id:
        raise ValueError("embedding event course does not match content version")

    version_dict = {
        "id": version_id,
        "course_id": course_id,
        "tenant_id": course.tenant_id,
    }

    indexed = 0
    while True:
        # Select scalar columns rather than ORM entities so the identity map cannot
        # retain an entire textbook-sized version. Updated rows stop matching this
        # query, making every page both bounded and naturally resumable.
        result = await session.execute(
            select(
                Chunk.id.label("chunk_id"),
                Chunk.source_id,
                Chunk.ordinal,
                Chunk.text,
                Chunk.anchor_type,
                Chunk.anchor_value,
                Chunk.chunk_class,
                Chunk.token_count,
                SourceDocument.relative_path,
                SourceDocument.mime_type,
                SourceDocument.access_label,
            )
            .join(SourceDocument)
            .join(ContentVersionSource, ContentVersionSource.source_id == SourceDocument.id)
            .where(
                ContentVersionSource.version_id == version_id,
                (Chunk.embedding_model_version.is_(None))
                | (Chunk.embedding_model_version == "pending")
                | (Chunk.embedding_model_version != embedding_model_version),
            )
            .order_by(Chunk.source_id, Chunk.ordinal)
            .limit(CHUNK_PAGE_SIZE)
        )
        rows = result.all()
        if not rows:
            break

        chunk_dicts = [
            {
                "id": row.chunk_id,
                "source_id": row.source_id,
                "ordinal": row.ordinal,
                "text": row.text,
                "anchor_type": row.anchor_type,
                "anchor_value": row.anchor_value,
                "chunk_class": row.chunk_class,
                "relative_path": row.relative_path,
                "mime_type": row.mime_type,
                "access_label": row.access_label,
                "token_count": row.token_count,
            }
            for row in rows
        ]
        indexed += await indexer.index_chunks(chunk_dicts, version_dict)
        await session.execute(
            update(Chunk)
            .where(Chunk.id.in_([row.chunk_id for row in rows]))
            .values(embedding_model_version=embedding_model_version)
        )
        await session.flush()

    if indexed == 0:
        logger.info("embedding_job_no_chunks", version_id=str(version_id))

    from course_tutor_contracts.enums import ContentVersionStatus

    version.status = ContentVersionStatus.READY
    version.embedding_model_version = embedding_model_version

    logger.info(
        "embedding_version_complete",
        version_id=str(version_id),
        chunks_indexed=indexed,
    )
    return EmbeddingStats(chunks_indexed=indexed, versions_indexed=1)
