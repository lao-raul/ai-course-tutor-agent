"""PostgreSQL repository for Hiruzen's isolated ``practice`` schema."""

from __future__ import annotations

import uuid
from datetime import UTC, datetime, timedelta
from uuid import UUID

from sqlalchemy import or_, select
from sqlalchemy.exc import IntegrityError
from sqlalchemy.ext.asyncio import AsyncSession

from course_tutor_contracts import ExerciseDraft, GenerationStatus
from course_tutor_practice.adapters.exercises import (
    exercise_view_from_storage,
    split_exercise_draft,
)
from course_tutor_practice.application.state_machine import require_transition
from course_tutor_practice.db.models import (
    Exercise,
    GenerationJob,
    PracticeOutboxEvent,
    PracticeSet,
    StudyPlan,
    StudyPlanModule,
)
from course_tutor_practice.domain import (
    GenerationRecord,
    ModuleRecord,
    PracticeSetRecord,
    StudyPlanRecord,
)


class SqlPracticeRepository:
    def __init__(self, session: AsyncSession) -> None:
        self._session = session

    async def _plan_record(self, model: StudyPlan) -> StudyPlanRecord:
        modules = (
            await self._session.scalars(
                select(StudyPlanModule)
                .where(StudyPlanModule.study_plan_id == model.id)
                .order_by(StudyPlanModule.ordinal)
            )
        ).all()
        return StudyPlanRecord(
            id=model.id,
            tenant_id=model.tenant_id,
            book_id=model.agent_book_id,
            course_id=model.agent_course_id,
            course_run_id=model.agent_course_run_id,
            content_version_id=model.agent_content_version_id,
            name=model.name,
            revision=model.revision,
            modules=tuple(
                ModuleRecord(
                    id=item.id,
                    ordinal=item.ordinal,
                    title=item.title,
                    outline_node_id=item.outline_node_id,
                    objectives=tuple(item.objectives),
                )
                for item in modules
            ),
            policy=dict(model.policy),
        )

    async def get_study_plan(
        self, tenant_id: UUID, book_id: UUID, content_version_id: UUID
    ) -> StudyPlanRecord | None:
        model = await self._session.scalar(
            select(StudyPlan).where(
                StudyPlan.tenant_id == tenant_id,
                StudyPlan.agent_book_id == book_id,
                StudyPlan.agent_content_version_id == content_version_id,
            )
        )
        return await self._plan_record(model) if model is not None else None

    async def find_study_plan_by_course(
        self, tenant_id: UUID, course_id: UUID
    ) -> StudyPlanRecord | None:
        model = await self._session.scalar(
            select(StudyPlan)
            .where(
                StudyPlan.tenant_id == tenant_id,
                StudyPlan.agent_course_id == course_id,
            )
            .order_by(StudyPlan.revision.desc(), StudyPlan.created_at.desc())
            .limit(1)
        )
        return await self._plan_record(model) if model is not None else None

    async def save_study_plan(self, plan: StudyPlanRecord) -> StudyPlanRecord:
        existing = await self.get_study_plan(plan.tenant_id, plan.book_id, plan.content_version_id)
        if existing is not None:
            return existing
        self._session.add(
            StudyPlan(
                id=plan.id,
                tenant_id=plan.tenant_id,
                agent_book_id=plan.book_id,
                agent_course_id=plan.course_id,
                agent_course_run_id=plan.course_run_id,
                agent_content_version_id=plan.content_version_id,
                name=plan.name,
                revision=plan.revision,
                policy=plan.policy,
            )
        )
        self._session.add_all(
            [
                StudyPlanModule(
                    id=module.id,
                    study_plan_id=plan.id,
                    ordinal=module.ordinal,
                    title=module.title,
                    outline_node_id=module.outline_node_id,
                    objectives=list(module.objectives),
                )
                for module in plan.modules
            ]
        )
        try:
            await self._session.commit()
        except IntegrityError:
            await self._session.rollback()
            existing = await self.get_study_plan(
                plan.tenant_id, plan.book_id, plan.content_version_id
            )
            if existing is None:
                raise
            return existing
        return plan

    async def _generation_record(self, model: GenerationJob) -> GenerationRecord:
        set_id = await self._session.scalar(
            select(PracticeSet.id).where(PracticeSet.generation_job_id == model.id)
        )
        return GenerationRecord(
            id=model.id,
            tenant_id=model.tenant_id,
            user_id=model.user_id,
            study_plan_id=model.study_plan_id,
            module_id=model.module_id,
            book_id=model.agent_book_id,
            course_id=model.agent_course_id,
            course_run_id=model.agent_course_run_id,
            content_version_id=model.agent_content_version_id,
            idempotency_key=model.idempotency_key,
            request_payload=dict(model.request_payload),
            requested_count=model.requested_count,
            status=GenerationStatus(model.status),
            correlation_id=model.correlation_id,
            deadline_at=model.deadline_at,
            attempt_count=model.attempt_count,
            created_at=model.created_at,
            updated_at=model.updated_at,
            practice_set_id=set_id,
            error_code=model.error_code,
            retryable=model.retryable,
        )

    async def submit_generation(
        self, generation: GenerationRecord
    ) -> tuple[GenerationRecord, bool]:
        existing = await self._session.scalar(
            select(GenerationJob).where(
                GenerationJob.tenant_id == generation.tenant_id,
                GenerationJob.user_id == generation.user_id,
                GenerationJob.idempotency_key == generation.idempotency_key,
            )
        )
        if existing is not None:
            return await self._generation_record(existing), False
        model = GenerationJob(
            id=generation.id,
            tenant_id=generation.tenant_id,
            user_id=generation.user_id,
            study_plan_id=generation.study_plan_id,
            module_id=generation.module_id,
            agent_book_id=generation.book_id,
            agent_course_id=generation.course_id,
            agent_course_run_id=generation.course_run_id,
            agent_content_version_id=generation.content_version_id,
            idempotency_key=generation.idempotency_key,
            request_payload=generation.request_payload,
            requested_count=generation.requested_count,
            status=generation.status.value,
            correlation_id=generation.correlation_id,
            deadline_at=generation.deadline_at,
            attempt_count=0,
        )
        event = PracticeOutboxEvent(
            id=uuid.uuid5(uuid.NAMESPACE_URL, f"generation-event:{generation.id}"),
            generation_job_id=generation.id,
            topic="practice.generate",
            idempotency_key=f"practice.generate:{generation.id}",
            payload={"generation_id": str(generation.id)},
            correlation_id=generation.correlation_id,
            attempts=0,
        )
        self._session.add_all([model, event])
        try:
            await self._session.commit()
        except IntegrityError:
            await self._session.rollback()
            existing = await self._session.scalar(
                select(GenerationJob).where(
                    GenerationJob.tenant_id == generation.tenant_id,
                    GenerationJob.user_id == generation.user_id,
                    GenerationJob.idempotency_key == generation.idempotency_key,
                )
            )
            if existing is None:
                raise
            return await self._generation_record(existing), False
        await self._session.refresh(model)
        return await self._generation_record(model), True

    async def get_generation(
        self, tenant_id: UUID, user_id: UUID, generation_id: UUID
    ) -> GenerationRecord | None:
        model = await self._session.scalar(
            select(GenerationJob).where(
                GenerationJob.id == generation_id,
                GenerationJob.tenant_id == tenant_id,
                GenerationJob.user_id == user_id,
            )
        )
        return await self._generation_record(model) if model is not None else None

    async def cancel_generation(
        self, tenant_id: UUID, user_id: UUID, generation_id: UUID
    ) -> GenerationRecord | None:
        model = await self._session.scalar(
            select(GenerationJob)
            .where(
                GenerationJob.id == generation_id,
                GenerationJob.tenant_id == tenant_id,
                GenerationJob.user_id == user_id,
            )
            .with_for_update()
        )
        if model is None:
            return None
        current = GenerationStatus(model.status)
        if current not in {
            GenerationStatus.READY,
            GenerationStatus.FAILED,
            GenerationStatus.CANCELLED,
        }:
            require_transition(current, GenerationStatus.CANCELLED)
            model.status = GenerationStatus.CANCELLED.value
            event = await self._session.scalar(
                select(PracticeOutboxEvent).where(PracticeOutboxEvent.generation_job_id == model.id)
            )
            if event is not None:
                event.processed_at = datetime.now(UTC)
                event.lease_owner = None
                event.lease_expires_at = None
            await self._session.commit()
            await self._session.refresh(model)
        return await self._generation_record(model)

    async def get_practice_set(
        self, tenant_id: UUID, user_id: UUID, set_id: UUID
    ) -> PracticeSetRecord | None:
        model = await self._session.scalar(
            select(PracticeSet).where(
                PracticeSet.id == set_id,
                PracticeSet.tenant_id == tenant_id,
                PracticeSet.user_id == user_id,
            )
        )
        if model is None:
            return None
        exercises = (
            await self._session.scalars(
                select(Exercise)
                .where(Exercise.practice_set_id == model.id)
                .order_by(Exercise.ordinal)
            )
        ).all()
        return PracticeSetRecord(
            id=model.id,
            generation_id=model.generation_job_id,
            tenant_id=model.tenant_id,
            user_id=model.user_id,
            study_plan_id=model.study_plan_id,
            book_id=model.agent_book_id,
            course_id=model.agent_course_id,
            content_version_id=model.agent_content_version_id,
            exercises=tuple(exercise_view_from_storage(item.presentation) for item in exercises),
            created_at=model.created_at,
        )

    async def claim_next_generation(
        self, worker_id: str, now: datetime, lease_duration: timedelta
    ) -> GenerationRecord | None:
        event = await self._session.scalar(
            select(PracticeOutboxEvent)
            .join(GenerationJob, GenerationJob.id == PracticeOutboxEvent.generation_job_id)
            .where(
                PracticeOutboxEvent.processed_at.is_(None),
                PracticeOutboxEvent.dead_lettered_at.is_(None),
                or_(
                    PracticeOutboxEvent.lease_expires_at.is_(None),
                    PracticeOutboxEvent.lease_expires_at <= now,
                ),
                GenerationJob.status.in_(["queued", "retrieving"]),
            )
            .order_by(PracticeOutboxEvent.created_at)
            .with_for_update(skip_locked=True)
            .limit(1)
        )
        if event is None:
            await self._session.rollback()
            return None
        job = await self._session.get(GenerationJob, event.generation_job_id)
        assert job is not None
        if job.deadline_at <= now:
            job.status = GenerationStatus.FAILED.value
            job.error_code = "deadline_exceeded"
            job.retryable = False
            event.dead_lettered_at = now
            event.last_error = "generation deadline exceeded"
            await self._session.commit()
            return None
        job.status = GenerationStatus.RETRIEVING.value
        job.attempt_count += 1
        job.lease_owner = worker_id
        job.lease_expires_at = now + lease_duration
        event.attempts += 1
        event.lease_owner = worker_id
        event.lease_expires_at = now + lease_duration
        await self._session.commit()
        await self._session.refresh(job)
        return await self._generation_record(job)

    async def transition_generation(
        self, generation_id: UUID, target: GenerationStatus
    ) -> GenerationRecord:
        model = await self._session.scalar(
            select(GenerationJob).where(GenerationJob.id == generation_id).with_for_update()
        )
        if model is None:
            raise LookupError("generation not found")
        require_transition(GenerationStatus(model.status), target)
        model.status = target.value
        await self._session.commit()
        await self._session.refresh(model)
        return await self._generation_record(model)

    async def retry_or_fail_generation(
        self,
        generation_id: UUID,
        error_code: str,
        detail: str,
        *,
        retryable: bool,
        max_attempts: int,
    ) -> GenerationRecord:
        model = await self._session.scalar(
            select(GenerationJob).where(GenerationJob.id == generation_id).with_for_update()
        )
        if model is None:
            raise LookupError("generation not found")
        event = await self._session.scalar(
            select(PracticeOutboxEvent).where(
                PracticeOutboxEvent.generation_job_id == generation_id
            )
        )
        target = (
            GenerationStatus.QUEUED
            if retryable and model.attempt_count < max_attempts
            else GenerationStatus.FAILED
        )
        require_transition(GenerationStatus(model.status), target)
        model.status = target.value
        model.error_code = error_code
        model.error_detail = detail[:2000]
        model.retryable = retryable
        model.lease_owner = None
        model.lease_expires_at = None
        if event is not None:
            event.last_error = detail[:2000]
            event.lease_owner = None
            event.lease_expires_at = None
            if target is GenerationStatus.FAILED:
                event.dead_lettered_at = datetime.now(UTC)
        await self._session.commit()
        await self._session.refresh(model)
        return await self._generation_record(model)

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
        existing_id = await self._session.scalar(
            select(PracticeSet.id).where(PracticeSet.generation_job_id == generation_id)
        )
        if existing_id is not None:
            existing = await self._session.get(PracticeSet, existing_id)
            assert existing is not None
            result = await self.get_practice_set(existing.tenant_id, existing.user_id, existing.id)
            assert result is not None
            return result
        job = await self._session.scalar(
            select(GenerationJob).where(GenerationJob.id == generation_id).with_for_update()
        )
        if job is None:
            raise LookupError("generation not found")
        if GenerationStatus(job.status) is not GenerationStatus.VALIDATING:
            raise ValueError("generation must be validating before completion")
        set_id = uuid.uuid5(uuid.NAMESPACE_URL, f"practice-set:{generation_id}")
        evidence_ids = sorted(
            {citation for draft in drafts for citation in draft.evidence_citation_ids}
        )
        model = PracticeSet(
            id=set_id,
            generation_job_id=job.id,
            tenant_id=job.tenant_id,
            user_id=job.user_id,
            study_plan_id=job.study_plan_id,
            agent_book_id=job.agent_book_id,
            agent_course_id=job.agent_course_id,
            agent_content_version_id=job.agent_content_version_id,
            seed=seed,
            prompt_version=prompt_version,
            model_version=model_version,
            validator_version=validator_version,
            evidence_chunk_ids=evidence_ids,
            correlation_id=job.correlation_id,
        )
        self._session.add(model)
        for ordinal, draft in enumerate(drafts):
            exercise_id = uuid.uuid5(uuid.NAMESPACE_URL, f"exercise:{set_id}:{ordinal}")
            presentation, protected, rationale, fingerprint, _view = split_exercise_draft(
                draft, exercise_id, ordinal
            )
            self._session.add(
                Exercise(
                    id=exercise_id,
                    practice_set_id=set_id,
                    ordinal=ordinal,
                    question_type=draft.type.value,
                    presentation=presentation,
                    protected_answer=protected,
                    rationale=rationale,
                    evidence_citation_ids=list(draft.evidence_citation_ids),
                    fingerprint=fingerprint,
                )
            )
        job.status = GenerationStatus.READY.value
        job.lease_owner = None
        job.lease_expires_at = None
        event = await self._session.scalar(
            select(PracticeOutboxEvent).where(
                PracticeOutboxEvent.generation_job_id == generation_id
            )
        )
        if event is not None:
            event.processed_at = datetime.now(UTC)
            event.lease_owner = None
            event.lease_expires_at = None
        await self._session.commit()
        result = await self.get_practice_set(job.tenant_id, job.user_id, set_id)
        assert result is not None
        return result
