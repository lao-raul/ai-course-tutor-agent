from __future__ import annotations

from typing import cast
from uuid import uuid4

import pytest
from course_tutor_practice_worker import GenerationExecutor, PracticeWorker

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
from course_tutor_practice.adapters.memory_repository import InMemoryPracticeRepository
from course_tutor_practice.application.generation import GenerationService
from course_tutor_practice.domain import ModuleRecord, StudyPlanRecord


class FakeExecutor:
    async def generate(self, _job):  # type: ignore[no-untyped-def]
        return (
            MultipleChoiceExerciseDraft(
                prompt="Choose the greeting.",
                difficulty=PracticeDifficulty.INTRODUCTORY,
                language=PracticeLanguage.EN,
                evidence_citation_ids=("chunk-1",),
                options=(
                    ChoiceOption(id="a", text="Hello"),
                    ChoiceOption(id="b", text="Goodbye"),
                ),
                correct_option_id="a",
                rationale="The cited dialogue starts with Hello.",
            ),
        )


@pytest.mark.asyncio
async def test_worker_completes_exactly_one_idempotent_practice_set() -> None:
    repository = InMemoryPracticeRepository()
    principal = Principal(
        user_id=uuid4(),
        tenant_id=uuid4(),
        role=UserRole.STUDENT,
        access_label=AccessLabel.ENROLLED,
        subject="worker-test",
    )
    plan = StudyPlanRecord(
        id=uuid4(),
        tenant_id=principal.tenant_id,
        book_id=uuid4(),
        course_id=uuid4(),
        course_run_id=uuid4(),
        content_version_id=uuid4(),
        name="Default",
        revision=1,
        modules=(ModuleRecord(id=uuid4(), ordinal=0, title="Book"),),
    )
    await repository.save_study_plan(plan)
    job, _ = await GenerationService(repository).submit(
        principal, plan, GeneratePracticeRequest(count=1), "worker-key", "corr"
    )
    worker = PracticeWorker(
        repository,
        cast("GenerationExecutor", FakeExecutor()),
        worker_id="worker-a",
    )
    assert await worker.run_once()
    completed = await repository.get_generation(principal.tenant_id, principal.user_id, job.id)
    assert completed is not None
    assert completed.status is GenerationStatus.READY
    assert completed.practice_set_id is not None
    assert await worker.run_once() is False
    assert len(repository.sets) == 1
