"""Ingestion worker CLI.

Usage:
    python -m course_tutor_ingestion.cli

Polls the outbox for pending ingestion.scan and ingestion.embed events and processes them.
Designed to run as a sidecar or background worker, not inline with the API.
"""

from __future__ import annotations

import asyncio
import signal
import sys
from typing import TYPE_CHECKING

from course_tutor_shared import (
    OUTBOX_DEPTH,
    Settings,
    configure_logging,
    configure_tracing,
    get_logger,
    get_settings,
    start_metrics_server,
)

configure_logging()
logger = get_logger(__name__)

if TYPE_CHECKING:
    from course_tutor_ingestion.object_store import MinioObjectStore


async def _configured_object_store(settings: Settings) -> MinioObjectStore | None:
    """Create artifact storage only when source replication is explicitly enabled."""
    if not settings.store_source_artifacts:
        return None
    from course_tutor_ingestion.object_store import MinioObjectStore

    object_store = MinioObjectStore(
        endpoint=settings.minio_endpoint,
        access_key=settings.minio_access_key,
        secret_key=settings.minio_secret_key.get_secret_value(),
        bucket=settings.minio_bucket,
    )
    await asyncio.to_thread(object_store.ensure_bucket)
    return object_store


async def main() -> None:
    # Lazy import to avoid circular dependency at module load time.
    # cli.py → course_tutor_api.dependencies → course_tutor_api.providers.lmstudio
    # has a transitive path that touches the ingestion package internals.
    from course_tutor_api.dependencies import get_dependencies
    from course_tutor_ingestion.embed_jobs import run_pending_embedding_jobs
    from course_tutor_ingestion.jobs import enqueue_due_scans, run_pending_jobs
    from course_tutor_ingestion.memory_jobs import (
        run_memory_retention_cleanup,
        run_pending_memory_purges,
    )

    settings = get_settings()
    configure_tracing(settings)
    if settings.metrics_enabled:
        start_metrics_server(settings.metrics_port)
    deps = get_dependencies(settings)
    object_store = await _configured_object_store(settings)

    logger.info(
        "ingestion_worker_start",
        poll_interval=settings.ingestion_poll_interval_seconds,
        artifact_storage="content-addressed" if object_store is not None else "source-root-only",
    )

    running = True

    def shutdown(signum: int, frame: object) -> None:
        nonlocal running
        logger.info("ingestion_worker_shutdown_requested")
        running = False

    signal.signal(signal.SIGINT, shutdown)
    signal.signal(signal.SIGTERM, shutdown)

    while running:
        from sqlalchemy.ext.asyncio import AsyncSession

        async with AsyncSession(deps.engine, expire_on_commit=False) as session:
            await enqueue_due_scans(session)
            # Process scan jobs
            processed_scans = await run_pending_jobs(
                session,
                max_batch=5,
                object_store=object_store,
                max_attempts=settings.ingestion_max_attempts,
            )
            if processed_scans:
                logger.info("ingestion_batch_complete", count=processed_scans)
            else:
                logger.debug("ingestion_worker_idle")

            # Process embedding jobs (uses Qdrant + LM Studio for embeddings)
            processed_embeds = await run_pending_embedding_jobs(
                session,
                max_batch=10,
                qdrant_client=deps.qdrant_client,
                embed_provider=deps.llm,
                embedding_model_version=settings.llm_embedding_model,
                max_attempts=settings.ingestion_max_attempts,
            )
            if processed_embeds:
                logger.info("embedding_batch_complete", count=processed_embeds)

            processed_purges = await run_pending_memory_purges(session)
            if processed_purges:
                logger.info("memory_purge_batch_complete", count=processed_purges)
            expired_sessions, expired_turns = await run_memory_retention_cleanup(
                session,
                chat_turn_retention_days=settings.chat_turn_retention_days,
            )
            if expired_sessions or expired_turns:
                logger.info(
                    "memory_retention_cleanup_complete",
                    sessions=expired_sessions,
                    turns=expired_turns,
                )

            from sqlalchemy import func, select

            from course_tutor_api.db import OutboxEvent

            known_topics = ("ingestion.scan", "ingestion.embed", "memory.purge")
            for topic in known_topics:
                pending_result = await session.execute(
                    select(func.count(OutboxEvent.id)).where(
                        OutboxEvent.topic == topic,
                        OutboxEvent.processed_at.is_(None),
                        OutboxEvent.dead_lettered_at.is_(None),
                    )
                )
                dead_result = await session.execute(
                    select(func.count(OutboxEvent.id)).where(
                        OutboxEvent.topic == topic,
                        OutboxEvent.dead_lettered_at.is_not(None),
                    )
                )
                metric_topic = topic.replace(".", "_")
                OUTBOX_DEPTH.labels("ingestion-worker", metric_topic, "pending").set(
                    int(pending_result.scalar_one())
                )
                OUTBOX_DEPTH.labels("ingestion-worker", metric_topic, "dead_letter").set(
                    int(dead_result.scalar_one())
                )

        if running:
            await asyncio.sleep(settings.ingestion_poll_interval_seconds)

    await deps.aclose()
    logger.info("ingestion_worker_stopped")


if __name__ == "__main__":
    sys.exit(asyncio.run(main()))
