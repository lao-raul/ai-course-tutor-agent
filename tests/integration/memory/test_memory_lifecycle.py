from __future__ import annotations

import uuid

import pytest
from course_tutor_ingestion.memory_jobs import run_pending_memory_purges
from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession

from course_tutor_api.auth import Principal
from course_tutor_api.db import (
    Course,
    MemoryFact,
    MemorySetting,
    Programme,
    SourceRoot,
    Tenant,
    User,
)
from course_tutor_api.memory_store import prepare_conversation
from course_tutor_api.routes.memories import export_memories, update_memory
from course_tutor_contracts.enums import (
    AccessLabel,
    EducationLevel,
    MemoryFactStatus,
    UserRole,
)
from course_tutor_contracts.memory import MemoryUpdate
from course_tutor_contracts.retrieval import ChatRequest
from course_tutor_shared import Settings
from course_tutor_shared.config import Environment


async def _seed(
    db_session: AsyncSession, *, memory_enabled: bool = True
) -> tuple[Principal, Course]:
    tenant_id, user_id, programme_id, course_id, root_id = (uuid.uuid4() for _ in range(5))
    db_session.add(Tenant(id=tenant_id, slug=f"memory-{tenant_id}", name="Memory Test"))
    await db_session.flush()
    db_session.add(
        User(
            id=user_id,
            tenant_id=tenant_id,
            external_subject=f"memory-{user_id}",
            display_name="Learner",
            role=UserRole.STUDENT,
        )
    )
    db_session.add(
        Programme(id=programme_id, tenant_id=tenant_id, code="MEM", name="Memory Programme")
    )
    db_session.add(
        SourceRoot(
            id=root_id,
            tenant_id=tenant_id,
            absolute_path="/generated",
            scan_interval_seconds=900,
        )
    )
    await db_session.flush()
    course = Course(
        id=course_id,
        tenant_id=tenant_id,
        programme_id=programme_id,
        code="MEM101",
        name="Memory",
        level=EducationLevel.POSTGRADUATE,
        source_root_id=root_id,
        teaching_policy={},
    )
    db_session.add(course)
    await db_session.flush()
    db_session.add(
        MemorySetting(
            id=uuid.uuid4(),
            user_id=user_id,
            course_id=course_id,
            enabled=memory_enabled,
        )
    )
    await db_session.commit()
    return (
        Principal(
            user_id=user_id,
            tenant_id=tenant_id,
            role=UserRole.STUDENT,
            access_label=AccessLabel.ENROLLED,
            subject="memory-student",
            course_ids=frozenset({course_id}),
        ),
        course,
    )


@pytest.mark.asyncio
async def test_repeated_preference_merges_provenance_and_session_scope_is_enforced(
    db_session: AsyncSession,
) -> None:
    principal, course = await _seed(db_session)
    settings = Settings(environment=Environment.TEST, memory_extraction_interval=1)
    first = await prepare_conversation(
        db_session,
        principal,
        course,
        ChatRequest(query="请用中文一步一步解释。"),
        settings,
    )
    await prepare_conversation(
        db_session,
        principal,
        course,
        ChatRequest(query="请用中文一步一步解释。", session_id=first.session_id),
        settings,
    )
    facts = (
        (
            await db_session.execute(
                select(MemoryFact).where(MemoryFact.user_id == principal.user_id)
            )
        )
        .scalars()
        .all()
    )
    assert {(fact.normalized_key, len(fact.evidence_turn_ids)) for fact in facts} == {
        ("response_language", 2),
        ("explanation_style", 2),
    }

    wrong_user = Principal(
        user_id=uuid.uuid4(),
        tenant_id=principal.tenant_id,
        role=UserRole.STUDENT,
        access_label=AccessLabel.ENROLLED,
        subject="wrong-user",
        course_ids=frozenset({course.id}),
    )
    with pytest.raises(ValueError, match="does not belong"):
        await prepare_conversation(
            db_session,
            wrong_user,
            course,
            ChatRequest(query="continue", session_id=first.session_id),
            settings,
        )


@pytest.mark.asyncio
async def test_opt_out_stores_turns_but_not_long_term_facts(
    db_session: AsyncSession,
) -> None:
    principal, course = await _seed(db_session, memory_enabled=False)
    await prepare_conversation(
        db_session,
        principal,
        course,
        ChatRequest(query="Please answer in English step-by-step."),
        Settings(environment=Environment.TEST, memory_extraction_interval=1),
    )
    assert (
        await db_session.scalar(select(MemoryFact).where(MemoryFact.user_id == principal.user_id))
        is None
    )


@pytest.mark.asyncio
async def test_conflicting_preference_is_not_silently_recalled(
    db_session: AsyncSession,
) -> None:
    principal, course = await _seed(db_session)
    settings = Settings(environment=Environment.TEST, memory_extraction_interval=1)
    first = await prepare_conversation(
        db_session,
        principal,
        course,
        ChatRequest(query="请用中文回答。"),
        settings,
    )
    second = await prepare_conversation(
        db_session,
        principal,
        course,
        ChatRequest(query="Please answer in English.", session_id=first.session_id),
        settings,
    )
    facts = (
        await db_session.execute(
            select(MemoryFact).where(
                MemoryFact.user_id == principal.user_id,
                MemoryFact.normalized_key == "response_language",
            )
        )
    ).scalars()
    assert {fact.status for fact in facts} == {MemoryFactStatus.CONFLICTED}
    assert all(
        fact.value != "chinese" and fact.value != "english" for fact in second.recalled_facts
    )


@pytest.mark.asyncio
async def test_correction_supersedes_old_fact_and_delete_tombstones_immediately(
    db_session: AsyncSession,
) -> None:
    principal, course = await _seed(db_session)
    settings = Settings(environment=Environment.TEST, memory_extraction_interval=1)
    await prepare_conversation(
        db_session,
        principal,
        course,
        ChatRequest(query="请用中文回答。"),
        settings,
    )
    fact = (
        await db_session.execute(select(MemoryFact).where(MemoryFact.user_id == principal.user_id))
    ).scalar_one()
    pinned = await update_memory(fact.id, MemoryUpdate(action="pin"), db_session, principal)
    assert pinned.pinned is True and pinned.expires_at is None
    exported = await export_memories(db_session, principal, course.id)
    assert exported.facts[0].reason.startswith("Validated")

    corrected = await update_memory(
        fact.id,
        MemoryUpdate(action="correct", normalized_value="bilingual"),
        db_session,
        principal,
    )
    assert corrected.normalized_value == "bilingual"
    assert (await db_session.get(MemoryFact, fact.id)).status == MemoryFactStatus.SUPERSEDED

    deleted = await update_memory(
        corrected.id, MemoryUpdate(action="delete"), db_session, principal
    )
    assert deleted.status == MemoryFactStatus.TOMBSTONED
    assert await run_pending_memory_purges(db_session) == 1
    assert await db_session.get(MemoryFact, corrected.id) is None
    assert await db_session.get(MemoryFact, fact.id) is None
