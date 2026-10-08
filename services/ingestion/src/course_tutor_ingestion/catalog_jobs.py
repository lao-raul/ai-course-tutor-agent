"""Outbox consumer for ChinaTextbook catalog scans."""

from __future__ import annotations

import uuid
from datetime import UTC, datetime
from pathlib import Path

import structlog
from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession

from course_tutor_api.db import OutboxEvent, SourceRoot
from course_tutor_ingestion.china_textbook_catalog import (
    ChinaTextbookCatalogScanner,
    stage_catalog_import,
)
from course_tutor_shared import INGESTION_JOBS, correlation_id_var

logger = structlog.get_logger(__name__)


async def run_pending_catalog_jobs(
    session: AsyncSession,
    *,
    max_batch: int = 5,
    max_attempts: int = 5,
) -> int:
    """Scan configured roots in the ingestion worker, never in the Agent API."""
    processed = 0
    for _ in range(max_batch):
        result = await session.execute(
            select(OutboxEvent)
            .where(
                OutboxEvent.topic == "catalog.scan",
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
        token = correlation_id_var.set(event.correlation_id or str(event.id))
        try:
            payload = dict(event.payload)
            source_root = await session.get(SourceRoot, uuid.UUID(payload["source_root_id"]))
            if source_root is None or str(source_root.tenant_id) != payload["tenant_id"]:
                raise ValueError("catalog source root is missing or crosses tenant boundary")
            scanner = ChinaTextbookCatalogScanner(
                Path(source_root.absolute_path),
                prefix=payload.get("prefix", "."),
                series_contains=payload.get("series_contains"),
            )
            batch = await stage_catalog_import(
                session,
                tenant_id=source_root.tenant_id,
                source_root_id=source_root.id,
                scanner=scanner,
            )
            payload["batch_id"] = str(batch.id)
            event.payload = payload
            event.processed_at = datetime.now(UTC).replace(tzinfo=None)
            await session.commit()
            INGESTION_JOBS.labels("ingestion-worker", "catalog_scan", "success").inc()
        except Exception as exc:
            await session.rollback()
            failed = await session.get(OutboxEvent, event_id, with_for_update=True)
            if failed is not None:
                failed.attempts += 1
                failed.last_error = str(exc)[:500]
                if failed.attempts >= max_attempts:
                    failed.dead_lettered_at = datetime.now(UTC).replace(tzinfo=None)
                await session.commit()
                outcome = "dead_letter" if failed.dead_lettered_at is not None else "retry"
                INGESTION_JOBS.labels("ingestion-worker", "catalog_scan", outcome).inc()
            logger.error("catalog_scan_failed", job_id=str(event_id), exc=str(exc))
        finally:
            correlation_id_var.reset(token)
    return processed


__all__ = ["run_pending_catalog_jobs"]
