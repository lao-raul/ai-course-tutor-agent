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
) -> int:
    """Claim and process up to *max_batch* pending ingestion.embed outbox events."""
    from course_tutor_retrieval.indexer import EmbeddingIndexer

    from course_tutor_api.db.models import OutboxEvent
    from course_tutor_ingestion.jobs import PIPELINE_VERSION

    result = await session.execute(
        select(OutboxEvent)
        .where(
            OutboxEvent.topic == "ingestion.embed",
            OutboxEvent.processed_at.is_(None),
            OutboxEvent.dead_lettered_at.is_(None),
        )
        .limit(max_batch)
    )
    events = list(result.scalars().all())
    indexer = EmbeddingIndexer(qdrant_client=qdrant_client, embed_provider=embed_provider)

    for event in events:
        try:
            stats = await _process_embed_event(session, event, indexer, PIPELINE_VERSION)
            event.processed_at = datetime.now(UTC).replace(tzinfo=None)
            await session.commit()
            logger.info(
                "embedding_job_complete",
                job_id=str(event.id),
                chunks_indexed=stats.chunks_indexed,
            )
        except Exception as exc:
            logger.error("embedding_job_crash", job_id=str(event.id), exc=str(exc))
            event.attempts += 1
            event.last_error = str(exc)[:500]
            if event.attempts >= 5:
                event.dead_lettered_at = datetime.now(UTC).replace(tzinfo=None)
            await session.commit()

    return len(events)


async def _process_embed_event(
    session: AsyncSession,
    event: Any,
    indexer: Any,
    pipeline_version: str,
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
            | (Chunk.embedding_model_version != pipeline_version),
        )
        .order_by(Chunk.source_id, Chunk.ordinal)
        .limit(10000)
    )
    chunks = list(result.scalars().all())
    if not chunks:
        logger.info("embedding_job_no_chunks", version_id=str(version_id))
        return EmbeddingStats()

    # Build chunk dicts for the indexer
    chunk_dicts = []
    for chunk in chunks:
        source = await session.get(SourceDocument, chunk.source_id)
        chunk_dicts.append(
            {
                "id": chunk.id,
                "source_id": chunk.source_id,
                "ordinal": chunk.ordinal,
                "text": chunk.text,
                "anchor_type": chunk.anchor_type,
                "anchor_value": chunk.anchor_value,
                "chunk_class": chunk.chunk_class,
                "relative_path": source.relative_path if source else "unknown",
                "mime_type": source.mime_type if source else "application/octet-stream",
                "access_label": source.access_label if source else "enrolled",
                "token_count": chunk.token_count,
            }
        )

    # Resolve tenant_id
    tenant_id = uuid.UUID("00000000-0000-0000-0000-000000000000")
    course = await session.get(Course, version.course_id)
    if course is not None:
        tenant_id = course.tenant_id

    version_dict = {
        "id": version_id,
        "course_id": course_id,
        "tenant_id": tenant_id,
    }

    indexed = await indexer.index_chunks(chunk_dicts, version_dict)

    # Mark chunks as indexed
    chunk_ids = [c.id for c in chunks]
    await session.execute(
        update(Chunk)
        .where(Chunk.id.in_(chunk_ids))
        .values(embedding_model_version=pipeline_version)
    )
    await session.commit()

    logger.info(
        "embedding_version_complete",
        version_id=str(version_id),
        chunks_indexed=indexed,
    )
    return EmbeddingStats(chunks_indexed=indexed, versions_indexed=1)
