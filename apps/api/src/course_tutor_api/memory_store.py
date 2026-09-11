"""PostgreSQL orchestration for bounded session and long-term learner memory."""

from __future__ import annotations

import uuid
from dataclasses import dataclass
from datetime import UTC, datetime, timedelta
from typing import Literal, cast

from course_tutor_memory import (
    MemoryCandidate,
    RecallFact,
    TeachingPolicy,
    Turn,
    bounded_recall,
    estimate_tokens,
    extract_memory_candidates,
    recent_turn_window,
    rolling_summary,
    semantic_similarity,
)
from sqlalchemy import func, select
from sqlalchemy.ext.asyncio import AsyncEngine, AsyncSession

from course_tutor_api.auth import Principal
from course_tutor_api.db import ChatSession, ChatTurn, Course, MemoryFact, MemorySetting
from course_tutor_contracts.enums import MemoryFactStatus, MemoryFactType
from course_tutor_contracts.retrieval import ChatRequest
from course_tutor_shared import Settings


@dataclass(frozen=True, slots=True)
class ConversationContext:
    session_id: uuid.UUID
    user_turn_id: uuid.UUID
    rolling_summary: str | None
    recent_turns: tuple[Turn, ...]
    recalled_facts: tuple[RecallFact, ...]
    teaching_policy: TeachingPolicy


def teaching_policy_for(course: Course, body: ChatRequest) -> TeachingPolicy:
    configured = dict(getattr(course, "teaching_policy", {}) or {})
    level = getattr(course, "level", None)
    configured.setdefault("education_level", getattr(level, "value", "postgraduate"))
    if body.response_language is not None:
        configured["response_language"] = body.response_language
    return TeachingPolicy.model_validate(configured)


def _expiry_for(candidate: MemoryCandidate, now: datetime) -> datetime:
    days = (
        90
        if candidate.type in {MemoryFactType.MISCONCEPTION, MemoryFactType.MASTERY_SIGNAL}
        else 365
    )
    return now + timedelta(days=days)


async def _promote_candidate(
    session: AsyncSession,
    principal: Principal,
    candidate: MemoryCandidate,
) -> MemoryFact:
    result = await session.execute(
        select(MemoryFact).where(
            MemoryFact.user_id == principal.user_id,
            MemoryFact.course_id == candidate.course_id,
            MemoryFact.type == candidate.type,
            MemoryFact.normalized_key == candidate.key,
            MemoryFact.status == MemoryFactStatus.ACTIVE,
        )
    )
    existing = result.scalar_one_or_none()
    now = datetime.now(UTC).replace(tzinfo=None)
    if existing is not None:
        evidence = list(dict.fromkeys([*existing.evidence_turn_ids, candidate.evidence_turn_id]))
        if semantic_similarity(existing.normalized_value, candidate.value) >= 0.9:
            existing.evidence_turn_ids = evidence
            existing.confidence = max(existing.confidence, candidate.confidence)
            existing.importance = max(existing.importance, candidate.importance)
            existing.last_confirmed_at = now
            existing.expires_at = _expiry_for(candidate, now)
            return existing

        # Contradictory values are retained for explicit learner confirmation and
        # neither value is silently recalled.
        existing.status = MemoryFactStatus.CONFLICTED
        await session.flush()
        conflicted = MemoryFact(
            id=uuid.uuid4(),
            user_id=principal.user_id,
            course_id=candidate.course_id,
            type=candidate.type,
            normalized_key=candidate.key,
            normalized_value=candidate.value,
            confidence=candidate.confidence,
            importance=candidate.importance,
            evidence_turn_ids=[candidate.evidence_turn_id],
            status=MemoryFactStatus.CONFLICTED,
            pinned=False,
            last_confirmed_at=now,
            expires_at=_expiry_for(candidate, now),
            supersedes_id=existing.id,
        )
        session.add(conflicted)
        return conflicted

    fact = MemoryFact(
        id=uuid.uuid4(),
        user_id=principal.user_id,
        course_id=candidate.course_id,
        type=candidate.type,
        normalized_key=candidate.key,
        normalized_value=candidate.value,
        confidence=candidate.confidence,
        importance=candidate.importance,
        evidence_turn_ids=[candidate.evidence_turn_id],
        status=MemoryFactStatus.ACTIVE,
        pinned=False,
        last_confirmed_at=now,
        expires_at=_expiry_for(candidate, now),
    )
    session.add(fact)
    return fact


async def _memory_enabled(
    session: AsyncSession, principal: Principal, course_id: uuid.UUID
) -> bool:
    result = await session.execute(
        select(MemorySetting.enabled).where(
            MemorySetting.user_id == principal.user_id,
            MemorySetting.course_id == course_id,
        )
    )
    return bool(result.scalar_one_or_none())


async def prepare_conversation(
    session: AsyncSession,
    principal: Principal,
    course: Course,
    body: ChatRequest,
    settings: Settings,
) -> ConversationContext:
    now = datetime.now(UTC).replace(tzinfo=None)
    if body.session_id is None:
        chat_session = ChatSession(
            id=uuid.uuid4(),
            user_id=principal.user_id,
            course_id=course.id,
            rolling_summary=None,
            summary_token_count=0,
            expires_at=now + timedelta(days=settings.session_summary_retention_days),
        )
        session.add(chat_session)
        await session.flush()
    else:
        loaded_session = await session.get(ChatSession, body.session_id)
        if (
            loaded_session is None
            or loaded_session.user_id != principal.user_id
            or loaded_session.course_id != course.id
            or (loaded_session.expires_at is not None and loaded_session.expires_at <= now)
        ):
            raise ValueError("chat session does not belong to the authenticated user and course")
        chat_session = loaded_session

    result = await session.execute(
        select(ChatTurn)
        .where(ChatTurn.session_id == chat_session.id)
        .order_by(ChatTurn.created_at.desc())
        .limit(64)
    )
    existing_turns = list(reversed(result.scalars().all()))
    context_turns = [
        Turn(
            id=item.id,
            role=cast(Literal["user", "assistant"], item.role),
            content=item.content,
        )
        for item in existing_turns
    ]

    user_turn = ChatTurn(
        id=uuid.uuid4(),
        session_id=chat_session.id,
        role="user",
        content=body.query,
        token_count=estimate_tokens(body.query),
    )
    session.add(user_turn)
    await session.flush()

    memory_enabled = await _memory_enabled(session, principal, course.id)
    if memory_enabled:
        user_turn_count = int(
            await session.scalar(
                select(func.count(ChatTurn.id)).where(
                    ChatTurn.session_id == chat_session.id,
                    ChatTurn.role == "user",
                )
            )
            or 0
        )
        candidates = extract_memory_candidates(
            body.query,
            turn_id=user_turn.id,
            course_id=course.id,
            meaningful_turn_number=user_turn_count,
            trigger_interval=settings.memory_extraction_interval,
        )
        for candidate in candidates:
            await _promote_candidate(session, principal, candidate)

    recent = recent_turn_window(context_turns)
    old_count = len(context_turns) - len(recent)
    if old_count:
        chat_session.rolling_summary = rolling_summary(
            chat_session.rolling_summary, context_turns[:old_count]
        )
        chat_session.summary_token_count = estimate_tokens(chat_session.rolling_summary)

    recalled: tuple[RecallFact, ...] = ()
    if memory_enabled:
        facts_result = await session.execute(
            select(MemoryFact).where(
                MemoryFact.user_id == principal.user_id,
                MemoryFact.course_id == course.id,
                MemoryFact.status == MemoryFactStatus.ACTIVE,
            )
        )
        recalled = bounded_recall(
            [
                RecallFact(
                    id=fact.id,
                    type=fact.type,
                    value=fact.normalized_value,
                    confidence=fact.confidence,
                    importance=fact.importance,
                    updated_at=fact.updated_at,
                    status=fact.status,
                    pinned=fact.pinned,
                    expires_at=fact.expires_at,
                )
                for fact in facts_result.scalars().all()
            ],
            body.query,
        )

    await session.commit()
    return ConversationContext(
        session_id=chat_session.id,
        user_turn_id=user_turn.id,
        rolling_summary=chat_session.rolling_summary,
        recent_turns=recent,
        recalled_facts=recalled,
        teaching_policy=teaching_policy_for(course, body),
    )


async def persist_assistant_turn(
    engine: AsyncEngine,
    session_id: uuid.UUID,
    content: str,
) -> None:
    if not content.strip():
        return
    async with AsyncSession(engine, expire_on_commit=False) as session:
        if await session.get(ChatSession, session_id) is None:
            return
        session.add(
            ChatTurn(
                id=uuid.uuid4(),
                session_id=session_id,
                role="assistant",
                content=content,
                token_count=estimate_tokens(content),
            )
        )
        await session.commit()


__all__ = [
    "ConversationContext",
    "persist_assistant_turn",
    "prepare_conversation",
    "teaching_policy_for",
]
