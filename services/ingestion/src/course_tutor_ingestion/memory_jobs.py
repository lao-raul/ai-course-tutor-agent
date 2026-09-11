"""Asynchronous purge of tombstoned memory and derived session summaries."""

from __future__ import annotations

import uuid
from datetime import UTC, datetime, timedelta

from sqlalchemy import delete, select, update
from sqlalchemy.ext.asyncio import AsyncSession

from course_tutor_api.db import ChatSession, ChatTurn, MemoryFact, OutboxEvent
from course_tutor_contracts.enums import MemoryFactStatus, MemoryFactType


async def run_pending_memory_purges(session: AsyncSession, *, max_batch: int = 10) -> int:
    processed = 0
    for _ in range(max_batch):
        result = await session.execute(
            select(OutboxEvent)
            .where(
                OutboxEvent.topic == "memory.purge",
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
        memory_id = uuid.UUID(str(event.payload["memory_id"]))
        user_id = uuid.UUID(str(event.payload["user_id"]))
        course_id = uuid.UUID(str(event.payload["course_id"]))
        delete_scope = [
            MemoryFact.user_id == user_id,
            MemoryFact.course_id == course_id,
            MemoryFact.status == MemoryFactStatus.TOMBSTONED,
        ]
        if event.payload.get("memory_type") and event.payload.get("normalized_key"):
            delete_scope.extend(
                [
                    MemoryFact.type == MemoryFactType(str(event.payload["memory_type"])),
                    MemoryFact.normalized_key == str(event.payload["normalized_key"]),
                ]
            )
        else:
            delete_scope.append(MemoryFact.id == memory_id)
        await session.execute(
            delete(MemoryFact).where(
                *delete_scope,
            )
        )
        # A summary may have incorporated the deleted preference. Clear the
        # rebuildable projection; retained turns can regenerate it safely.
        await session.execute(
            update(ChatSession)
            .where(ChatSession.user_id == user_id, ChatSession.course_id == course_id)
            .values(rolling_summary=None, summary_token_count=0)
        )
        event.processed_at = datetime.now(UTC).replace(tzinfo=None)
        event.last_error = None
        await session.commit()
        processed += 1
    return processed


async def run_memory_retention_cleanup(
    session: AsyncSession,
    *,
    chat_turn_retention_days: int,
    now: datetime | None = None,
) -> tuple[int, int]:
    """Remove expired sessions and raw turns past their configured retention."""
    current = (now or datetime.now(UTC)).replace(tzinfo=None)
    sessions_result = await session.execute(
        delete(ChatSession).where(
            ChatSession.expires_at.is_not(None), ChatSession.expires_at <= current
        )
    )
    turns_result = await session.execute(
        delete(ChatTurn).where(
            ChatTurn.created_at < current - timedelta(days=chat_turn_retention_days)
        )
    )
    await session.commit()
    return (
        int(getattr(sessions_result, "rowcount", 0) or 0),
        int(getattr(turns_result, "rowcount", 0) or 0),
    )


__all__ = ["run_memory_retention_cleanup", "run_pending_memory_purges"]
