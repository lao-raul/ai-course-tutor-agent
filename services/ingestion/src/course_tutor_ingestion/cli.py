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

from course_tutor_shared import configure_logging, get_logger, get_settings

configure_logging()
logger = get_logger(__name__)

POLL_INTERVAL_SECONDS = 5


async def main() -> None:
    # Lazy import to avoid circular dependency at module load time.
    # cli.py → course_tutor_api.dependencies → course_tutor_api.providers.lmstudio
    # has a transitive path that touches the ingestion package internals.
    from course_tutor_api.dependencies import get_dependencies
    from course_tutor_ingestion.embed_jobs import run_pending_embedding_jobs
    from course_tutor_ingestion.jobs import run_pending_jobs
    from course_tutor_ingestion.object_store import MinioObjectStore

    settings = get_settings()
    deps = get_dependencies(settings)
    object_store = MinioObjectStore(
        endpoint=settings.minio_endpoint,
        access_key=settings.minio_access_key,
        secret_key=settings.minio_secret_key.get_secret_value(),
        bucket="course-tutor-artifacts",
    )

    logger.info("ingestion_worker_start", poll_interval=POLL_INTERVAL_SECONDS)

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
            # Process scan jobs
            processed_scans = await run_pending_jobs(
                session, max_batch=5, object_store=object_store
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
            )
            if processed_embeds:
                logger.info("embedding_batch_complete", count=processed_embeds)

        if running:
            await asyncio.sleep(POLL_INTERVAL_SECONDS)

    await deps.aclose()
    logger.info("ingestion_worker_stopped")


if __name__ == "__main__":
    sys.exit(asyncio.run(main()))
