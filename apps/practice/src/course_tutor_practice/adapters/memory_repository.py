"""Deterministic repository for unit tests and contract-only development."""

from __future__ import annotations

import asyncio
import uuid
from dataclasses import replace
from datetime import UTC, datetime, timedelta
from uuid import UUID

from course_tutor_contracts import (
    ExerciseDraft,
    ExerciseReportView,
    GenerationStatus,
    StudySetProgressView,
)
from course_tutor_practice.adapters.exercises import split_exercise_draft
from course_tutor_practice.application.state_machine import require_transition
from course_tutor_practice.domain import GenerationRecord, PracticeSetRecord, StudyPlanRecord
from course_tutor_practice.domain.attempts import (
    AttemptConflict,
    AttemptRecord,
    Evaluation,
    ExerciseMaterial,
)
from course_tutor_practice.domain.study import ActivityRecord, project_set


class InMemoryPracticeRepository:
    def __init__(self) -> None:
        self.plans: dict[UUID, StudyPlanRecord] = {}
        self.generations: dict[UUID, GenerationRecord] = {}
        self.idempotency: dict[tuple[UUID, UUID, str], UUID] = {}
        self.sets: dict[UUID, PracticeSetRecord] = {}
        self.leases: dict[UUID, tuple[str, datetime]] = {}
        self.materials: dict[UUID, ExerciseMaterial] = {}
        self.attempts: list[AttemptRecord] = []
        self.activities: list[ActivityRecord] = []
        self.progress: dict[tuple[UUID, UUID, UUID], StudySetProgressView] = {}
        self.cursors: dict[tuple[UUID, UUID], tuple[UUID | None, bool]] = {}
        self.reports: dict[tuple[UUID, UUID, UUID, str], ExerciseReportView] = {}
        self._report_payloads: dict[tuple[UUID, UUID, UUID, str], tuple[str, str]] = {}
        self._reset_keys: set[tuple[UUID, UUID, str]] = set()
        self.memory_consent: dict[tuple[UUID, UUID], bool] = {}
        self._attempt_lock = asyncio.Lock()

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
        retrieval_trace_id: UUID | None = None,
    ) -> PracticeSetRecord:
        del seed, prompt_version, model_version, validator_version, retrieval_trace_id
        job = self.generations[generation_id]
        if existing := next(
            (value for value in self.sets.values() if value.generation_id == generation_id), None
        ):
            return existing
        if job.status is not GenerationStatus.VALIDATING:
            raise ValueError("generation must be validating before completion")
        if len(drafts) != job.requested_count:
            raise ValueError("generation count mismatch")
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
        for ordinal, draft in enumerate(drafts):
            exercise_id = views[ordinal].id
            _presentation, protected, rationale, _fingerprint, _view = split_exercise_draft(
                draft, exercise_id, ordinal
            )
            self.materials[exercise_id] = ExerciseMaterial(
                tenant_id=job.tenant_id,
                user_id=job.user_id,
                set_id=set_id,
                study_plan_id=job.study_plan_id,
                book_id=job.book_id,
                course_id=job.course_id,
                content_version_id=job.content_version_id,
                exercise_id=exercise_id,
                view=views[ordinal],
                protected_answer=protected,
                rationale=rationale,
            )
        ready = replace(
            job,
            status=GenerationStatus.READY,
            practice_set_id=record.id,
            updated_at=datetime.now(UTC),
        )
        self.generations[job.id] = ready
        self.leases.pop(job.id, None)
        return record

    async def get_material(
        self, tenant_id: UUID, user_id: UUID, set_id: UUID, exercise_id: UUID
    ) -> ExerciseMaterial | None:
        material = self.materials.get(exercise_id)
        if (
            material is None
            or (material.tenant_id, material.user_id, material.set_id)
            != (
                tenant_id,
                user_id,
                set_id,
            )
            or await self.get_practice_set(tenant_id, user_id, set_id) is None
        ):
            return None
        return material

    async def find_material(
        self, tenant_id: UUID, user_id: UUID, exercise_id: UUID
    ) -> ExerciseMaterial | None:
        material = self.materials.get(exercise_id)
        if material is None:
            return None
        return await self.get_material(tenant_id, user_id, material.set_id, exercise_id)

    async def get_attempts(
        self, tenant_id: UUID, user_id: UUID, exercise_id: UUID
    ) -> tuple[AttemptRecord, ...]:
        return tuple(
            item
            for item in self.attempts
            if (item.tenant_id, item.user_id, item.exercise_id) == (tenant_id, user_id, exercise_id)
        )

    async def record_attempt(
        self,
        material: ExerciseMaterial,
        *,
        action: str,
        answer: str | bool | None,
        digest: str,
        idempotency_key: str,
        evaluation: Evaluation,
    ) -> AttemptRecord:
        async with self._attempt_lock:
            attempts = await self.get_attempts(
                material.tenant_id, material.user_id, material.exercise_id
            )
            existing = next(
                (item for item in attempts if item.idempotency_key == idempotency_key), None
            )
            if existing is not None:
                if existing.request_digest != digest:
                    raise AttemptConflict("idempotency key was used with a different answer")
                return existing
            if (
                any(item.action == "give_up" for item in attempts)
                or sum(item.action == "submit" for item in attempts) >= 3
                or (
                    action == "submit" and any(item.evaluation.correct is True for item in attempts)
                )
            ):
                raise AttemptConflict("exercise is already complete")
            now = datetime.now(UTC)
            record = AttemptRecord(
                id=uuid.uuid4(),
                tenant_id=material.tenant_id,
                user_id=material.user_id,
                set_id=material.set_id,
                exercise_id=material.exercise_id,
                attempt_number=len(attempts) + 1,
                action=action,
                idempotency_key=idempotency_key,
                answer=answer,
                request_digest=digest,
                evaluation=evaluation,
                created_at=now,
            )
            self.attempts.append(record)
            self.activities.append(
                ActivityRecord(
                    id=uuid.uuid4(),
                    set_id=material.set_id,
                    exercise_id=material.exercise_id,
                    event_type="answer_submitted" if action == "submit" else "gave_up",
                    created_at=now,
                )
            )
            projection = await self.rebuild_progress(
                material.tenant_id, material.user_id, material.set_id
            )
            self.cursors[(material.tenant_id, material.user_id)] = (
                material.set_id if projection and projection.next_exercise_id else None,
                False,
            )
            return record

    async def rebuild_progress(
        self, tenant_id: UUID, user_id: UUID, set_id: UUID
    ) -> StudySetProgressView | None:
        practice_set = await self.get_practice_set(tenant_id, user_id, set_id)
        if practice_set is None:
            return None
        job = self.generations[practice_set.generation_id]
        projection = project_set(
            set_id=set_id,
            study_plan_id=practice_set.study_plan_id,
            book_id=practice_set.book_id,
            course_id=practice_set.course_id,
            content_version_id=practice_set.content_version_id,
            exercise_ids=tuple(item.id for item in practice_set.exercises),
            attempts=tuple(
                item for item in self.attempts if item.set_id == set_id and item.user_id == user_id
            ),
            activities=tuple(item for item in self.activities if item.set_id == set_id),
            module_id=job.module_id,
        )
        self.progress[(tenant_id, user_id, set_id)] = projection
        return projection

    async def list_progress(
        self, tenant_id: UUID, user_id: UUID
    ) -> tuple[StudySetProgressView, ...]:
        result = []
        for practice_set in self.sets.values():
            if (practice_set.tenant_id, practice_set.user_id) == (tenant_id, user_id):
                result.append(
                    self.progress.get((tenant_id, user_id, practice_set.id))
                    or await self.rebuild_progress(tenant_id, user_id, practice_set.id)
                )
        return tuple(item for item in result if item is not None)

    async def get_cursor(self, tenant_id: UUID, user_id: UUID) -> tuple[UUID | None, bool]:
        return self.cursors.get((tenant_id, user_id), (None, False))

    async def reset_cursor(self, tenant_id: UUID, user_id: UUID, key: str) -> None:
        lookup = (tenant_id, user_id, key)
        if lookup in self._reset_keys:
            return
        self._reset_keys.add(lookup)
        self.activities.append(
            ActivityRecord(
                id=uuid.uuid4(),
                set_id=None,
                exercise_id=None,
                event_type="resume_reset",
                created_at=datetime.now(UTC),
            )
        )
        self.cursors[(tenant_id, user_id)] = (None, True)

    async def save_report(
        self, material: ExerciseMaterial, reason: str, detail: str, key: str
    ) -> ExerciseReportView:
        lookup = (material.tenant_id, material.user_id, material.exercise_id, key)
        if lookup in self._report_payloads and self._report_payloads[lookup] != (reason, detail):
            raise AttemptConflict("idempotency key was used with a different report")
        if lookup not in self.reports:
            self.reports[lookup] = ExerciseReportView(
                id=uuid.uuid4(), exercise_id=material.exercise_id, created_at=datetime.now(UTC)
            )
            self._report_payloads[lookup] = (reason, detail)
        return self.reports[lookup]

    async def get_memory_consent(self, tenant_id: UUID, user_id: UUID) -> bool:
        return self.memory_consent.get((tenant_id, user_id), False)

    async def set_memory_consent(self, tenant_id: UUID, user_id: UUID, enabled: bool) -> None:
        self.memory_consent[(tenant_id, user_id)] = enabled
