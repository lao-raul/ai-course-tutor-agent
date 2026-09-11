"""Learner-controlled long-term-memory inspection and lifecycle APIs."""

from __future__ import annotations

import uuid
from datetime import UTC, datetime
from typing import Annotated

from fastapi import APIRouter, Depends, HTTPException, Query, status
from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession

from course_tutor_api.auth import Principal, get_current_principal, principal_can_access_course
from course_tutor_api.db import AuditEvent, Course, MemoryFact, MemorySetting, OutboxEvent
from course_tutor_api.dependencies import get_session
from course_tutor_contracts.enums import MemoryFactStatus
from course_tutor_contracts.memory import (
    MemoryConsentUpdate,
    MemoryConsentView,
    MemoryExport,
    MemoryFactView,
    MemoryUpdate,
)

router = APIRouter(prefix="/v1", tags=["memory"])


async def _course(session: AsyncSession, principal: Principal, course_id: uuid.UUID) -> Course:
    course = await session.get(Course, course_id)
    if (
        course is None
        or course.tenant_id != principal.tenant_id
        or not principal_can_access_course(principal, course_id)
    ):
        raise HTTPException(status_code=status.HTTP_404_NOT_FOUND, detail="course not found")
    return course


def _audit(
    session: AsyncSession,
    principal: Principal,
    action: str,
    resource_id: uuid.UUID | str,
) -> None:
    session.add(
        AuditEvent(
            id=uuid.uuid4(),
            tenant_id=principal.tenant_id,
            actor_user_id=principal.user_id,
            action=action,
            resource_type="memory_fact",
            resource_id=str(resource_id),
            details={},
        )
    )


def _view(fact: MemoryFact) -> MemoryFactView:
    if fact.course_id is None:
        raise ValueError("v0.2 memory facts must be course scoped")
    return MemoryFactView(
        id=fact.id,
        course_id=fact.course_id,
        type=fact.type,
        normalized_key=fact.normalized_key,
        normalized_value=fact.normalized_value,
        confidence=fact.confidence,
        importance=fact.importance,
        status=fact.status,
        pinned=fact.pinned,
        evidence_turn_ids=tuple(fact.evidence_turn_ids),
        created_at=fact.created_at,
        updated_at=fact.updated_at,
        expires_at=fact.expires_at,
        reason=(
            f"Validated {fact.type.value} supported by "
            f"{len(fact.evidence_turn_ids)} conversation turn(s)."
        ),
    )


async def _owned_fact(
    session: AsyncSession, principal: Principal, memory_id: uuid.UUID
) -> MemoryFact:
    fact = await session.get(MemoryFact, memory_id)
    if fact is None or fact.user_id != principal.user_id or fact.course_id is None:
        raise HTTPException(status_code=404, detail="memory not found")
    await _course(session, principal, fact.course_id)
    return fact


@router.get("/memories", response_model=list[MemoryFactView], operation_id="listMemories")
async def list_memories(
    session: Annotated[AsyncSession, Depends(get_session)],
    principal: Annotated[Principal, Depends(get_current_principal)],
    course_id: Annotated[uuid.UUID, Query()],
) -> list[MemoryFactView]:
    await _course(session, principal, course_id)
    result = await session.execute(
        select(MemoryFact)
        .where(
            MemoryFact.user_id == principal.user_id,
            MemoryFact.course_id == course_id,
            MemoryFact.status != MemoryFactStatus.TOMBSTONED,
        )
        .order_by(MemoryFact.pinned.desc(), MemoryFact.updated_at.desc())
    )
    return [_view(fact) for fact in result.scalars().all()]


@router.get("/memories/export", response_model=MemoryExport, operation_id="exportMemories")
async def export_memories(
    session: Annotated[AsyncSession, Depends(get_session)],
    principal: Annotated[Principal, Depends(get_current_principal)],
    course_id: Annotated[uuid.UUID, Query()],
) -> MemoryExport:
    facts = await list_memories(session, principal, course_id)
    return MemoryExport(exported_at=datetime.now(UTC), course_id=course_id, facts=tuple(facts))


@router.put(
    "/courses/{course_id}/memory-consent",
    response_model=MemoryConsentView,
    operation_id="setMemoryConsent",
)
async def set_memory_consent(
    course_id: uuid.UUID,
    body: MemoryConsentUpdate,
    session: Annotated[AsyncSession, Depends(get_session)],
    principal: Annotated[Principal, Depends(get_current_principal)],
) -> MemoryConsentView:
    await _course(session, principal, course_id)
    result = await session.execute(
        select(MemorySetting).where(
            MemorySetting.user_id == principal.user_id,
            MemorySetting.course_id == course_id,
        )
    )
    setting = result.scalar_one_or_none()
    if setting is None:
        setting = MemorySetting(
            id=uuid.uuid4(), user_id=principal.user_id, course_id=course_id, enabled=body.enabled
        )
        session.add(setting)
    else:
        setting.enabled = body.enabled
    _audit(session, principal, "memory.consent.update", course_id)
    response = MemoryConsentView(course_id=course_id, enabled=setting.enabled)
    await session.commit()
    return response


@router.get(
    "/courses/{course_id}/memory-consent",
    response_model=MemoryConsentView,
    operation_id="getMemoryConsent",
)
async def get_memory_consent(
    course_id: uuid.UUID,
    session: Annotated[AsyncSession, Depends(get_session)],
    principal: Annotated[Principal, Depends(get_current_principal)],
) -> MemoryConsentView:
    await _course(session, principal, course_id)
    result = await session.execute(
        select(MemorySetting.enabled).where(
            MemorySetting.user_id == principal.user_id,
            MemorySetting.course_id == course_id,
        )
    )
    return MemoryConsentView(course_id=course_id, enabled=bool(result.scalar_one_or_none()))


@router.patch("/memories/{memory_id}", response_model=MemoryFactView, operation_id="updateMemory")
async def update_memory(
    memory_id: uuid.UUID,
    body: MemoryUpdate,
    session: Annotated[AsyncSession, Depends(get_session)],
    principal: Annotated[Principal, Depends(get_current_principal)],
) -> MemoryFactView:
    fact = await _owned_fact(session, principal, memory_id)
    now = datetime.now(UTC).replace(tzinfo=None)
    if body.action == "pin":
        fact.pinned = True
        fact.expires_at = None
    elif body.action == "unpin":
        fact.pinned = False
    elif body.action == "delete":
        lineage_result = await session.execute(
            select(MemoryFact).where(
                MemoryFact.user_id == fact.user_id,
                MemoryFact.course_id == fact.course_id,
                MemoryFact.type == fact.type,
                MemoryFact.normalized_key == fact.normalized_key,
                MemoryFact.status != MemoryFactStatus.TOMBSTONED,
            )
        )
        for lineage_fact in lineage_result.scalars().all():
            lineage_fact.status = MemoryFactStatus.TOMBSTONED
            lineage_fact.tombstoned_at = now
        session.add(
            OutboxEvent(
                id=uuid.uuid4(),
                topic="memory.purge",
                idempotency_key=f"memory-purge:{fact.id}",
                payload={
                    "tenant_id": str(principal.tenant_id),
                    "user_id": str(principal.user_id),
                    "memory_id": str(fact.id),
                    "course_id": str(fact.course_id),
                    "memory_type": fact.type.value,
                    "normalized_key": fact.normalized_key,
                },
                attempts=0,
            )
        )
    else:
        assert body.normalized_value is not None
        fact.status = MemoryFactStatus.SUPERSEDED
        await session.flush()
        replacement = MemoryFact(
            id=uuid.uuid4(),
            user_id=fact.user_id,
            course_id=fact.course_id,
            type=fact.type,
            normalized_key=fact.normalized_key,
            normalized_value=body.normalized_value,
            confidence=1.0,
            importance=fact.importance,
            evidence_turn_ids=list(fact.evidence_turn_ids),
            status=MemoryFactStatus.ACTIVE,
            pinned=fact.pinned,
            last_confirmed_at=now,
            expires_at=fact.expires_at,
            supersedes_id=fact.id,
        )
        session.add(replacement)
        fact = replacement
    _audit(session, principal, f"memory.{body.action}", fact.id)
    await session.flush()
    await session.refresh(fact)
    response = _view(fact)
    await session.commit()
    return response
