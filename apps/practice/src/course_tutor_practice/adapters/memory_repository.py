"""Deterministic repository for unit tests and contract-only development."""

from __future__ import annotations

import uuid
from dataclasses import replace
from datetime import UTC, datetime, timedelta
from uuid import UUID

from course_tutor_contracts import ExerciseDraft, GenerationStatus
from course_tutor_practice.adapters.exercises import split_exercise_draft
from course_tutor_practice.application.state_machine import require_transition
from course_tutor_practice.domain import GenerationRecord, PracticeSetRecord, StudyPlanRecord


class InMemoryPracticeRepository:
    def __init__(self) -> None:
        self.plans: dict[UUID, StudyPlanRecord] = {}
        self.generations: dict[UUID, GenerationRecord] = {}
        self.idempotency: dict[tuple[UUID, UUID, str], UUID] = {}
        self.sets: dict[UUID, PracticeSetRecord] = {}
        self.leases: dict[UUID, tuple[str, datetime]] = {}

    async def get_study_plan(
        self, tenant_id: UUID, book_id: UUID, content_version_id: UUID
    ) -> StudyPlanRecord | None:
        return next(
            (
                plan
                for plan in self.plans.values()
                if plan.tenant_id == tenant_id
                and plan.book_id == book_id
                and plan.content_version_id == content_version_id
            ),
            None,
        )

    async def find_study_plan_by_course(
        self, tenant_id: UUID, course_id: UUID
    ) -> StudyPlanRecord | None:
        matches = [
            plan
            for plan in self.plans.values()
            if plan.tenant_id == tenant_id and plan.course_id == course_id
        ]
        return max(matches, key=lambda item: item.revision) if matches else None

    async def save_study_plan(self, plan: StudyPlanRecord) -> StudyPlanRecord:
        existing = await self.get_study_plan(plan.tenant_id, plan.book_id, plan.content_version_id)
        if existing is not None:
            return existing
        self.plans[plan.id] = plan
        return plan

    async def submit_generation(
        self, generation: GenerationRecord
    ) -> tuple[GenerationRecord, bool]:
        key = (generation.tenant_id, generation.user_id, generation.idempotency_key)
        if existing_id := self.idempotency.get(key):
            return self.generations[existing_id], False
        self.idempotency[key] = generation.id
        self.generations[generation.id] = generation
        return generation, True

    async def get_generation(
        self, tenant_id: UUID, user_id: UUID, generation_id: UUID
    ) -> GenerationRecord | None:
        job = self.generations.get(generation_id)
        if job is None or job.tenant_id != tenant_id or job.user_id != user_id:
            return None
        return job

    async def cancel_generation(
        self, tenant_id: UUID, user_id: UUID, generation_id: UUID
    ) -> GenerationRecord | None:
        job = await self.get_generation(tenant_id, user_id, generation_id)
        if job is None:
            return None
        if job.status in {GenerationStatus.READY, GenerationStatus.FAILED}:
            return job
        if job.status is not GenerationStatus.CANCELLED:
            require_transition(job.status, GenerationStatus.CANCELLED)
            job = replace(job, status=GenerationStatus.CANCELLED, updated_at=datetime.now(UTC))
            self.generations[job.id] = job
        return job

    async def get_practice_set(
        self, tenant_id: UUID, user_id: UUID, set_id: UUID
    ) -> PracticeSetRecord | None:
        value = self.sets.get(set_id)
        if value is None or value.tenant_id != tenant_id or value.user_id != user_id:
            return None
        return value

    async def claim_next_generation(
        self, worker_id: str, now: datetime, lease_duration: timedelta
    ) -> GenerationRecord | None:
        for job in sorted(self.generations.values(), key=lambda item: item.created_at):
            if job.status not in {GenerationStatus.QUEUED, GenerationStatus.RETRIEVING}:
                continue
            lease = self.leases.get(job.id)
            if lease is not None and lease[1] > now:
                continue
            if job.deadline_at <= now:
                failed = replace(
                    job,
                    status=GenerationStatus.FAILED,
                    error_code="deadline_exceeded",
                    retryable=False,
                    updated_at=now,
                )
                self.generations[job.id] = failed
                continue
            status = GenerationStatus.RETRIEVING
            claimed = replace(
                job,
                status=status,
                attempt_count=job.attempt_count + 1,
                updated_at=now,
            )
            self.generations[job.id] = claimed
            self.leases[job.id] = (worker_id, now + lease_duration)
            return claimed
        return None

    async def transition_generation(
        self, generation_id: UUID, target: GenerationStatus
    ) -> GenerationRecord:
        job = self.generations[generation_id]
        require_transition(job.status, target)
        job = replace(job, status=target, updated_at=datetime.now(UTC))
        self.generations[job.id] = job
        return job

    async def retry_or_fail_generation(
        self,
        generation_id: UUID,
        error_code: str,
        detail: str,
        *,
        retryable: bool,
        max_attempts: int,
    ) -> GenerationRecord:
        del detail
        job = self.generations[generation_id]
        target = (
            GenerationStatus.QUEUED
            if retryable and job.attempt_count < max_attempts
            else GenerationStatus.FAILED
        )
        require_transition(job.status, target)
        job = replace(
            job,
            status=target,
            error_code=error_code,
            retryable=retryable,
            updated_at=datetime.now(UTC),
        )
        self.generations[job.id] = job
        self.leases.pop(job.id, None)
        return job

    async def complete_generation(
        self,
        generation_id: UUID,
        drafts: tuple[ExerciseDraft, ...],
        *,
        seed: int,
        prompt_version: str,
        model_version: str,
        validator_version: str,
    ) -> PracticeSetRecord:
        del seed, prompt_version, model_version, validator_version
        job = self.generations[generation_id]
        if existing := next(
            (value for value in self.sets.values() if value.generation_id == generation_id), None
        ):
            return existing
        if job.status is not GenerationStatus.VALIDATING:
            raise ValueError("generation must be validating before completion")
        set_id = uuid.uuid5(uuid.NAMESPACE_URL, f"practice-set:{generation_id}")
        views = tuple(
            split_exercise_draft(
                draft,
                uuid.uuid5(uuid.NAMESPACE_URL, f"exercise:{set_id}:{ordinal}"),
                ordinal,
            )[4]
            for ordinal, draft in enumerate(drafts)
        )
        record = PracticeSetRecord(
            id=set_id,
            generation_id=job.id,
            tenant_id=job.tenant_id,
            user_id=job.user_id,
            study_plan_id=job.study_plan_id,
            book_id=job.book_id,
            course_id=job.course_id,
            content_version_id=job.content_version_id,
            exercises=views,
            created_at=datetime.now(UTC),
        )
        self.sets[record.id] = record
        ready = replace(
            job,
            status=GenerationStatus.READY,
            practice_set_id=record.id,
            updated_at=datetime.now(UTC),
        )
        self.generations[job.id] = ready
        self.leases.pop(job.id, None)
        return record
