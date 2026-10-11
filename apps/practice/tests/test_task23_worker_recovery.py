"""A restarted consumer must reclaim an accepted job from every in-flight phase."""

from datetime import UTC, datetime, timedelta
from uuid import uuid4

import pytest

from course_tutor_auth import Principal
from course_tutor_contracts import GeneratePracticeRequest, GenerationStatus
from course_tutor_contracts.enums import AccessLabel, UserRole
from course_tutor_practice.adapters.memory_repository import InMemoryPracticeRepository
from course_tutor_practice.application.generation import GenerationService
from course_tutor_practice.domain import ModuleRecord, StudyPlanRecord


@pytest.mark.asyncio
@pytest.mark.parametrize("phase", [GenerationStatus.GENERATING, GenerationStatus.VALIDATING])
async def test_expired_lease_reclaims_inflight_generation(phase: GenerationStatus) -> None:
    repository = InMemoryPracticeRepository()
    tenant_id, user_id, book_id, course_id = (uuid4() for _ in range(4))
    plan = StudyPlanRecord(
        id=uuid4(),
        tenant_id=tenant_id,
        book_id=book_id,
        course_id=course_id,
        course_run_id=uuid4(),
        content_version_id=uuid4(),
        name="fixture",
        revision=1,
        modules=(ModuleRecord(id=uuid4(), ordinal=0, title="Unit 1"),),
    )
    await repository.save_study_plan(plan)
    principal = Principal(
        user_id=user_id,
        tenant_id=tenant_id,
        role=UserRole.STUDENT,
        access_label=AccessLabel.ENROLLED,
        subject="learner",
        course_ids=frozenset({course_id}),
    )
    job, _ = await GenerationService(repository).submit(
        principal, plan, GeneratePracticeRequest(count=1), "recovery-key", "corr"
    )
    now = datetime.now(UTC)
    assert await repository.claim_next_generation("worker-a", now, timedelta(seconds=1))
    await repository.transition_generation(job.id, GenerationStatus.GENERATING)
    if phase is GenerationStatus.VALIDATING:
        await repository.transition_generation(job.id, phase)
    assert (
        await repository.claim_next_generation(
            "worker-b", now + timedelta(milliseconds=500), timedelta(seconds=1)
        )
        is None
    )
    recovered = await repository.claim_next_generation(
        "worker-b", now + timedelta(seconds=2), timedelta(seconds=1)
    )
    assert recovered is not None
    assert recovered.id == job.id
    assert recovered.status is GenerationStatus.RETRIEVING
    assert recovered.attempt_count == 2
