"""PostgreSQL TASK-21 atomic replay, projection and schema isolation tests."""

from __future__ import annotations

import asyncio
import uuid
from datetime import UTC, datetime, timedelta

import pytest
from sqlalchemy import delete, func, select
from sqlalchemy.ext.asyncio import AsyncEngine, AsyncSession

from course_tutor_auth import Principal
from course_tutor_contracts import (
    ChoiceOption,
    GeneratePracticeRequest,
    GenerationStatus,
    MultipleChoiceExerciseDraft,
    PracticeDifficulty,
    PracticeLanguage,
)
from course_tutor_contracts.enums import AccessLabel, UserRole
from course_tutor_practice.application.evaluation import evaluate
from course_tutor_practice.application.generation import GenerationService
from course_tutor_practice.db import Attempt, Base, StudyActivity, StudyProgress
from course_tutor_practice.db.repository import SqlPracticeRepository
from course_tutor_practice.db.study_repository import SqlStudyRepository
from course_tutor_practice.domain import ModuleRecord, StudyPlanRecord
from course_tutor_practice.domain.attempts import AttemptConflict


async def _seed(engine: AsyncEngine) -> tuple[Principal, uuid.UUID, uuid.UUID]:
    async with engine.begin() as connection:
        await connection.exec_driver_sql("CREATE SCHEMA IF NOT EXISTS practice")
        await connection.run_sync(Base.metadata.create_all)
    principal = Principal(
        user_id=uuid.uuid4(),
        tenant_id=uuid.uuid4(),
        role=UserRole.STUDENT,
        access_label=AccessLabel.ENROLLED,
        subject="sql-study-test",
    )
    plan = StudyPlanRecord(
        id=uuid.uuid4(),
        tenant_id=principal.tenant_id,
        book_id=uuid.uuid4(),
        course_id=uuid.uuid4(),
        course_run_id=uuid.uuid4(),
        content_version_id=uuid.uuid4(),
        name="Unit 1",
        revision=1,
        modules=(ModuleRecord(id=uuid.uuid4(), ordinal=0, title="Unit 1"),),
    )
    async with AsyncSession(engine, expire_on_commit=False) as session:
        generation = SqlPracticeRepository(session)
        await generation.save_study_plan(plan)
        job, _ = await GenerationService(generation).submit(
            principal, plan, GeneratePracticeRequest(count=1), "seed", "task21-test"
        )
        await generation.claim_next_generation("worker", datetime.now(UTC), timedelta(seconds=30))
        await generation.transition_generation(job.id, GenerationStatus.GENERATING)
        await generation.transition_generation(job.id, GenerationStatus.VALIDATING)
        result = await generation.complete_generation(
            job.id,
            (
                MultipleChoiceExerciseDraft(
                    prompt="Which is a greeting?",
                    difficulty=PracticeDifficulty.STANDARD,
                    language=PracticeLanguage.EN,
                    evidence_citation_ids=(str(uuid.uuid4()),),
                    rationale="The textbook says Hello is a greeting.",
                    options=(
                        ChoiceOption(id="a", text="Hello"),
                        ChoiceOption(id="b", text="Goodbye"),
                    ),
                    correct_option_id="a",
                ),
            ),
            seed=42,
            prompt_version="test",
            model_version="fake",
            validator_version="test",
        )
    return principal, result.id, result.exercises[0].id


@pytest.mark.asyncio
async def test_sql_replay_projection_rebuild_report_and_consent(
    integration_db_engine: AsyncEngine,
) -> None:
    principal, set_id, exercise_id = await _seed(integration_db_engine)
    async with AsyncSession(integration_db_engine, expire_on_commit=False) as session:
        repo = SqlStudyRepository(session)
        material = await repo.get_material(
            principal.tenant_id, principal.user_id, set_id, exercise_id
        )
        assert material is not None
        assert material.protected_answer == {"correct_option_id": "a"}
        grade = await evaluate(material, "b", None, "test")
        first = await repo.record_attempt(
            material,
            action="submit",
            answer="b",
            digest="wrong-answer-digest",
            idempotency_key="try-1",
            evaluation=grade,
        )
        replay = await repo.record_attempt(
            material,
            action="submit",
            answer="b",
            digest="wrong-answer-digest",
            idempotency_key="try-1",
            evaluation=grade,
        )
        assert replay.id == first.id
        with pytest.raises(AttemptConflict):
            await repo.record_attempt(
                material,
                action="submit",
                answer="a",
                digest="different-digest",
                idempotency_key="try-1",
                evaluation=grade,
            )
        assert (
            await session.scalar(
                select(func.count()).select_from(Attempt).where(Attempt.practice_set_id == set_id)
            )
            == 1
        )
        assert (
            await session.scalar(
                select(func.count())
                .select_from(StudyActivity)
                .where(StudyActivity.practice_set_id == set_id)
            )
            == 1
        )
        before = (await repo.list_progress(principal.tenant_id, principal.user_id))[0]
        assert before.attempted_questions == 1
        assert before.completed_questions == 0
        await session.execute(delete(StudyProgress).where(StudyProgress.practice_set_id == set_id))
        await session.commit()
        rebuilt = await repo.rebuild_progress(principal.tenant_id, principal.user_id, set_id)
        assert rebuilt == before
        report = await repo.save_report(material, "ambiguous", "Please review", "report-1")
        assert (
            await repo.save_report(material, "ambiguous", "Please review", "report-1")
        ).id == report.id
        assert await repo.get_memory_consent(principal.tenant_id, principal.user_id) is False
        await repo.set_memory_consent(principal.tenant_id, principal.user_id, True)
        assert await repo.get_memory_consent(principal.tenant_id, principal.user_id) is True
        await repo.reset_cursor(principal.tenant_id, principal.user_id, "reset-1")
        assert await repo.get_cursor(principal.tenant_id, principal.user_id) == (None, True)
        assert (
            await session.scalar(
                select(func.count()).select_from(Attempt).where(Attempt.practice_set_id == set_id)
            )
            == 1
        )


@pytest.mark.asyncio
async def test_concurrent_sql_submissions_are_serialized_per_set(
    integration_db_engine: AsyncEngine,
) -> None:
    principal, set_id, exercise_id = await _seed(integration_db_engine)

    async def submit(key: str) -> int:
        async with AsyncSession(integration_db_engine, expire_on_commit=False) as session:
            repo = SqlStudyRepository(session)
            material = await repo.get_material(
                principal.tenant_id, principal.user_id, set_id, exercise_id
            )
            assert material is not None
            grade = await evaluate(material, "b", None, "test")
            attempt = await repo.record_attempt(
                material,
                action="submit",
                answer="b",
                digest="wrong-answer-digest",
                idempotency_key=key,
                evaluation=grade,
            )
            return attempt.attempt_number

    assert sorted(await asyncio.gather(submit("one"), submit("two"))) == [1, 2]
    async with AsyncSession(integration_db_engine) as session:
        assert (
            await session.scalar(
                select(func.count()).select_from(Attempt).where(Attempt.practice_set_id == set_id)
            )
            == 2
        )
        assert (
            await session.scalar(
                select(func.count())
                .select_from(StudyActivity)
                .where(StudyActivity.practice_set_id == set_id)
            )
            == 2
        )
