from __future__ import annotations

import asyncio
import os
import subprocess
import sys
import uuid
from dataclasses import replace
from datetime import UTC, datetime, timedelta
from pathlib import Path

import pytest
from sqlalchemy import func, select, text
from sqlalchemy.ext.asyncio import AsyncEngine, AsyncSession, create_async_engine

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
from course_tutor_practice.application.generation import GenerationService
from course_tutor_practice.db import Base, GenerationJob, PracticeOutboxEvent, PracticeSet
from course_tutor_practice.db.repository import SqlPracticeRepository
from course_tutor_practice.domain import ModuleRecord, StudyPlanRecord
from course_tutor_practice.generation.errors import GenerationFailure
from course_tutor_practice.generation.schemas import GenerationObjective
from tests.support.postgres import assert_safe_test_database_dsn, reset_test_schema

ROOT = Path(__file__).resolve().parents[3]


def test_practice_migration_upgrade_downgrade_upgrade_round_trip() -> None:
    dsn = os.environ.get("TEST_POSTGRES_DSN")
    if not dsn:
        pytest.skip("TEST_POSTGRES_DSN is required; use scripts/run-integration-tests.sh")
    assert_safe_test_database_dsn(dsn)

    async def prepare_disposable_database() -> None:
        engine = create_async_engine(dsn)
        try:
            await reset_test_schema(engine, dsn)
            async with engine.begin() as connection:
                await connection.execute(text("DROP SCHEMA IF EXISTS practice CASCADE"))
        finally:
            await engine.dispose()

    asyncio.run(prepare_disposable_database())
    env = {**os.environ, "PRACTICE_POSTGRES_DSN": dsn}
    command = [sys.executable, "-m", "alembic", "-c", "apps/practice/alembic.ini"]
    for target in (("upgrade", "head"), ("downgrade", "base"), ("upgrade", "head")):
        subprocess.run(  # noqa: S603 - executable and all arguments are fixed locally
            [*command, *target],
            cwd=ROOT,
            env=env,
            check=True,
            capture_output=True,
            text=True,
        )

    async def verify_immutable_triggers() -> None:
        engine = create_async_engine(dsn)
        try:
            async with engine.connect() as connection:
                count = await connection.scalar(
                    text(
                        "SELECT count(*) FROM pg_trigger WHERE tgname = 'reject_immutable_write' "
                        "AND tgrelid IN ('practice.attempts'::regclass, "
                        "'practice.study_activity'::regclass)"
                    )
                )
                assert count == 2
        finally:
            await engine.dispose()

    asyncio.run(verify_immutable_triggers())


@pytest.mark.asyncio
async def test_sql_repository_commits_job_and_outbox_atomically(
    integration_db_engine: AsyncEngine,
) -> None:
    async with integration_db_engine.begin() as connection:
        await connection.execute(text("CREATE SCHEMA IF NOT EXISTS practice"))
        await connection.run_sync(Base.metadata.create_all)
    principal = Principal(
        user_id=uuid.uuid4(),
        tenant_id=uuid.uuid4(),
        role=UserRole.STUDENT,
        access_label=AccessLabel.ENROLLED,
        subject="integration-learner",
    )
    plan = StudyPlanRecord(
        id=uuid.uuid4(),
        tenant_id=principal.tenant_id,
        book_id=uuid.uuid4(),
        course_id=uuid.uuid4(),
        course_run_id=uuid.uuid4(),
        content_version_id=uuid.uuid4(),
        name="Default plan",
        revision=1,
        modules=(ModuleRecord(id=uuid.uuid4(), ordinal=0, title="Whole book"),),
    )
    async with AsyncSession(integration_db_engine, expire_on_commit=False) as session:
        repository = SqlPracticeRepository(session)
        await repository.save_study_plan(plan)
        service = GenerationService(repository)
        first, first_created = await service.submit(
            principal, plan, GeneratePracticeRequest(count=1), "same-key", "corr"
        )
        replay, replay_created = await service.submit(
            principal, plan, GeneratePracticeRequest(count=7), "same-key", "corr-2"
        )
        assert first_created is True
        assert replay_created is False
        assert first.id == replay.id
        assert replay.requested_count == 1
        assert await session.scalar(select(func.count()).select_from(GenerationJob)) == 1
        assert await session.scalar(select(func.count()).select_from(PracticeOutboxEvent)) == 1

        claimed_at = datetime.now(UTC)
        claimed = await repository.claim_next_generation(
            "worker-a", claimed_at, timedelta(seconds=30)
        )
        assert claimed is not None and claimed.status is GenerationStatus.RETRIEVING
        await repository.transition_generation(first.id, GenerationStatus.GENERATING)
        await repository.transition_generation(first.id, GenerationStatus.VALIDATING)
        assert await repository.renew_generation_lease(
            first.id, "worker-a", claimed_at + timedelta(seconds=20), timedelta(seconds=30)
        )
        assert (
            await repository.claim_next_generation(
                "worker-b", claimed_at + timedelta(seconds=31), timedelta(seconds=30)
            )
            is None
        )
        # Simulate a terminated worker after the validation transition. A new
        # consumer must reclaim the committed outbox event after lease expiry.
        recovered = await repository.claim_next_generation(
            "worker-b", claimed_at + timedelta(seconds=51), timedelta(seconds=30)
        )
        assert recovered is not None and recovered.id == first.id
        assert recovered.status is GenerationStatus.RETRIEVING
        assert recovered.attempt_count == 2
        await repository.transition_generation(first.id, GenerationStatus.GENERATING)
        await repository.transition_generation(first.id, GenerationStatus.VALIDATING)
        trace_id = uuid.uuid4()
        draft = MultipleChoiceExerciseDraft(
            prompt="Which word is a greeting?",
            difficulty=PracticeDifficulty.STANDARD,
            language=PracticeLanguage.ZH,
            evidence_citation_ids=(str(uuid.uuid4()),),
            rationale="The cited passage says Hello is a greeting.",
            options=(
                ChoiceOption(id="a", text="Hello"),
                ChoiceOption(id="b", text="Goodbye"),
            ),
            correct_option_id="a",
        )
        await repository.complete_generation(
            first.id,
            (draft,),
            seed=42,
            prompt_version="hiruzen-grounded-v1",
            model_version="fake",
            validator_version="hiruzen-validation-v1",
            retrieval_trace_id=trace_id,
            objectives=(GenerationObjective("Identify Hello as a greeting", "answer-key-hello"),),
        )
        stored = await session.scalar(
            select(PracticeSet).where(PracticeSet.generation_job_id == first.id)
        )
        assert stored is not None
        assert stored.retrieval_trace_id == trace_id
        assert stored.seed == 42
        assert stored.objective_metadata == [
            {
                "learning_objective": "Identify Hello as a greeting",
                "answer_key": "answer-key-hello",
                "answer_keys": [],
            }
        ]
        assert await repository.list_recent_objectives(first) == (
            GenerationObjective("Identify Hello as a greeting", "answer-key-hello"),
        )
        assert await repository.list_recent_objectives(replace(first, user_id=uuid.uuid4())) == ()
        second, created = await service.submit(
            principal, plan, GeneratePracticeRequest(count=1), "second-key", "corr-3"
        )
        assert created
        claimed_second = await repository.claim_next_generation(
            "worker-b", datetime.now(UTC), timedelta(seconds=30)
        )
        assert claimed_second is not None and claimed_second.id == second.id
        await repository.transition_generation(second.id, GenerationStatus.GENERATING)
        await repository.transition_generation(second.id, GenerationStatus.VALIDATING)
        with pytest.raises(GenerationFailure, match="duplicate_objective"):
            await repository.complete_generation(
                second.id,
                (draft,),
                seed=43,
                prompt_version="test",
                model_version="fake",
                validator_version="test",
                objectives=(
                    GenerationObjective("Recognize Hello as a greeting", "answer-key-hello"),
                ),
            )
        assert await session.scalar(select(func.count()).select_from(PracticeSet)) == 1


def test_practice_metadata_has_no_agent_schema_foreign_keys() -> None:
    for table in Base.metadata.tables.values():
        assert table.schema == "practice"
        for foreign_key in table.foreign_keys:
            assert foreign_key.target_fullname.startswith("practice.")
