"""Transactional learner-study persistence in the isolated Practice schema."""

from __future__ import annotations

import uuid
from uuid import UUID

from sqlalchemy import func, select
from sqlalchemy.dialects.postgresql import insert as pg_insert
from sqlalchemy.ext.asyncio import AsyncSession

from course_tutor_contracts import ExerciseReportView, StudySetProgressView
from course_tutor_practice.adapters.exercises import exercise_view_from_storage
from course_tutor_practice.db.models import (
    Attempt,
    Exercise,
    ExerciseReport,
    GenerationJob,
    PracticeSet,
    ResumeCursor,
    StudyActivity,
    StudyMemoryConsent,
    StudyProgress,
)
from course_tutor_practice.domain.attempts import (
    AttemptConflict,
    AttemptRecord,
    Evaluation,
    ExerciseMaterial,
)
from course_tutor_practice.domain.study import ActivityRecord, project_set


class SqlStudyRepository:
    def __init__(self, session: AsyncSession) -> None:
        self._session = session

    @staticmethod
    def _attempt_record(row: Attempt) -> AttemptRecord:
        return AttemptRecord(
            id=row.id,
            tenant_id=row.tenant_id,
            user_id=row.user_id,
            set_id=row.practice_set_id,
            exercise_id=row.exercise_id,
            attempt_number=row.attempt_number,
            action=row.action,
            idempotency_key=row.idempotency_key,
            answer=row.submitted_value,
            request_digest=row.request_digest,
            evaluation=Evaluation(
                correct=row.correct,
                score=row.score,
                provisional=row.provisional,
                evaluator=row.evaluator,
                evaluator_version=row.evaluator_version,
            ),
            created_at=row.created_at,
        )

    async def get_material(
        self, tenant_id: UUID, user_id: UUID, set_id: UUID, exercise_id: UUID
    ) -> ExerciseMaterial | None:
        row = await self._session.execute(
            select(PracticeSet, Exercise)
            .join(Exercise, Exercise.practice_set_id == PracticeSet.id)
            .where(
                PracticeSet.id == set_id,
                PracticeSet.tenant_id == tenant_id,
                PracticeSet.user_id == user_id,
                Exercise.id == exercise_id,
            )
        )
        result = row.one_or_none()
        if result is None:
            return None
        practice_set, exercise = result
        return ExerciseMaterial(
            tenant_id=tenant_id,
            user_id=user_id,
            set_id=set_id,
            study_plan_id=practice_set.study_plan_id,
            book_id=practice_set.agent_book_id,
            course_id=practice_set.agent_course_id,
            content_version_id=practice_set.agent_content_version_id,
            exercise_id=exercise_id,
            view=exercise_view_from_storage(exercise.presentation),
            protected_answer=dict(exercise.protected_answer),
            rationale=exercise.rationale,
        )

    async def find_material(
        self, tenant_id: UUID, user_id: UUID, exercise_id: UUID
    ) -> ExerciseMaterial | None:
        set_id = await self._session.scalar(
            select(PracticeSet.id)
            .join(Exercise, Exercise.practice_set_id == PracticeSet.id)
            .where(
                PracticeSet.tenant_id == tenant_id,
                PracticeSet.user_id == user_id,
                Exercise.id == exercise_id,
            )
        )
        return await self.get_material(tenant_id, user_id, set_id, exercise_id) if set_id else None

    async def get_attempts(
        self, tenant_id: UUID, user_id: UUID, exercise_id: UUID
    ) -> tuple[AttemptRecord, ...]:
        rows = (
            await self._session.scalars(
                select(Attempt)
                .where(
                    Attempt.tenant_id == tenant_id,
                    Attempt.user_id == user_id,
                    Attempt.exercise_id == exercise_id,
                )
                .order_by(Attempt.attempt_number)
            )
        ).all()
        return tuple(self._attempt_record(row) for row in rows)

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
        # Serialise every exercise in a set, so attempt ordinals and the set projection
        # cannot race even when two different exercises are submitted concurrently.
        owned_set = await self._session.scalar(
            select(PracticeSet)
            .where(
                PracticeSet.id == material.set_id,
                PracticeSet.tenant_id == material.tenant_id,
                PracticeSet.user_id == material.user_id,
            )
            .with_for_update()
        )
        if owned_set is None:
            raise LookupError("practice set not found")
        existing = await self._session.scalar(
            select(Attempt).where(
                Attempt.tenant_id == material.tenant_id,
                Attempt.user_id == material.user_id,
                Attempt.exercise_id == material.exercise_id,
                Attempt.idempotency_key == idempotency_key,
            )
        )
        if existing is not None:
            if existing.request_digest != digest:
                raise AttemptConflict("idempotency key was used with a different answer")
            return self._attempt_record(existing)
        previous = await self.get_attempts(
            material.tenant_id, material.user_id, material.exercise_id
        )
        if (
            any(item.action == "give_up" for item in previous)
            or sum(item.action == "submit" for item in previous) >= 3
            or (action == "submit" and any(item.evaluation.correct is True for item in previous))
        ):
            raise AttemptConflict("exercise is already complete")
        row = Attempt(
            id=uuid.uuid4(),
            tenant_id=material.tenant_id,
            user_id=material.user_id,
            practice_set_id=material.set_id,
            exercise_id=material.exercise_id,
            attempt_number=len(previous) + 1,
            action=action,
            idempotency_key=idempotency_key,
            request_digest=digest,
            submitted_value=answer,
            correct=evaluation.correct,
            score=evaluation.score,
            provisional=evaluation.provisional,
            evaluator=evaluation.evaluator,
            evaluator_version=evaluation.evaluator_version,
        )
        activity = StudyActivity(
            id=uuid.uuid4(),
            tenant_id=material.tenant_id,
            user_id=material.user_id,
            practice_set_id=material.set_id,
            exercise_id=material.exercise_id,
            event_type="answer_submitted" if action == "submit" else "gave_up",
            source_key=f"attempt:{row.id}",
        )
        self._session.add_all((row, activity))
        await self._session.flush()
        projection = await self._compute_projection(owned_set)
        await self._save_projection(projection, material.tenant_id, material.user_id)
        await self._session.execute(
            pg_insert(ResumeCursor)
            .values(
                id=uuid.uuid4(),
                tenant_id=material.tenant_id,
                user_id=material.user_id,
                practice_set_id=material.set_id if projection.next_exercise_id else None,
                exercise_id=projection.next_exercise_id,
                cleared=False,
            )
            .on_conflict_do_update(
                index_elements=["tenant_id", "user_id"],
                set_={
                    "practice_set_id": material.set_id if projection.next_exercise_id else None,
                    "exercise_id": projection.next_exercise_id,
                    "cleared": False,
                    "updated_at": func.now(),
                },
            )
        )
        await self._session.commit()
        return self._attempt_record(row)

    async def _compute_projection(self, practice_set: PracticeSet) -> StudySetProgressView:
        exercises = (
            await self._session.scalars(
                select(Exercise)
                .where(Exercise.practice_set_id == practice_set.id)
                .order_by(Exercise.ordinal)
            )
        ).all()
        attempts = (
            await self._session.scalars(
                select(Attempt).where(
                    Attempt.tenant_id == practice_set.tenant_id,
                    Attempt.user_id == practice_set.user_id,
                    Attempt.practice_set_id == practice_set.id,
                )
            )
        ).all()
        activities = (
            await self._session.scalars(
                select(StudyActivity).where(
                    StudyActivity.tenant_id == practice_set.tenant_id,
                    StudyActivity.user_id == practice_set.user_id,
                    StudyActivity.practice_set_id == practice_set.id,
                )
            )
        ).all()
        module_id = await self._session.scalar(
            select(GenerationJob.module_id).where(
                GenerationJob.id == practice_set.generation_job_id
            )
        )
        return project_set(
            set_id=practice_set.id,
            study_plan_id=practice_set.study_plan_id,
            book_id=practice_set.agent_book_id,
            course_id=practice_set.agent_course_id,
            content_version_id=practice_set.agent_content_version_id,
            exercise_ids=tuple(row.id for row in exercises),
            attempts=tuple(self._attempt_record(row) for row in attempts),
            activities=tuple(
                ActivityRecord(
                    row.id, practice_set.id, row.exercise_id, row.event_type, row.created_at
                )
                for row in activities
                if row.exercise_id is not None
            ),
            module_id=module_id,
        )

    async def _save_projection(
        self, value: StudySetProgressView, tenant_id: UUID, user_id: UUID
    ) -> None:
        payload = {
            "status": value.status,
            "total_questions": value.total_questions,
            "attempted_questions": value.attempted_questions,
            "completed_questions": value.completed_questions,
            "correct_questions": value.correct_questions,
            "next_exercise_id": value.next_exercise_id,
            "latest_activity_at": value.latest_activity_at,
            "topic_mastery": value.topic_mastery,
            "updated_at": func.now(),
        }
        statement = pg_insert(StudyProgress).values(
            id=uuid.uuid4(),
            tenant_id=tenant_id,
            user_id=user_id,
            practice_set_id=value.practice_set_id,
            **payload,
        )
        await self._session.execute(
            statement.on_conflict_do_update(
                index_elements=["tenant_id", "user_id", "practice_set_id"],
                set_=payload,
            )
        )

    async def rebuild_progress(
        self, tenant_id: UUID, user_id: UUID, set_id: UUID
    ) -> StudySetProgressView | None:
        practice_set = await self._session.scalar(
            select(PracticeSet)
            .where(
                PracticeSet.id == set_id,
                PracticeSet.tenant_id == tenant_id,
                PracticeSet.user_id == user_id,
            )
            .with_for_update()
        )
        if practice_set is None:
            return None
        value = await self._compute_projection(practice_set)
        await self._save_projection(value, tenant_id, user_id)
        await self._session.commit()
        return value

    async def list_progress(
        self, tenant_id: UUID, user_id: UUID
    ) -> tuple[StudySetProgressView, ...]:
        sets = (
            await self._session.scalars(
                select(PracticeSet)
                .where(PracticeSet.tenant_id == tenant_id, PracticeSet.user_id == user_id)
                .order_by(PracticeSet.created_at.desc())
            )
        ).all()
        return tuple([await self._compute_projection(item) for item in sets])

    async def get_cursor(self, tenant_id: UUID, user_id: UUID) -> tuple[UUID | None, bool]:
        cursor = await self._session.scalar(
            select(ResumeCursor).where(
                ResumeCursor.tenant_id == tenant_id, ResumeCursor.user_id == user_id
            )
        )
        return (cursor.practice_set_id, cursor.cleared) if cursor else (None, False)

    async def reset_cursor(self, tenant_id: UUID, user_id: UUID, key: str) -> None:
        source_key = f"resume-reset:{key}"
        statement = pg_insert(StudyActivity).values(
            id=uuid.uuid4(),
            tenant_id=tenant_id,
            user_id=user_id,
            practice_set_id=None,
            exercise_id=None,
            event_type="resume_reset",
            source_key=source_key,
        )
        result = await self._session.execute(
            statement.on_conflict_do_nothing(
                index_elements=["tenant_id", "user_id", "source_key"]
            ).returning(StudyActivity.id)
        )
        if result.scalar_one_or_none() is not None:
            await self._session.execute(
                pg_insert(ResumeCursor)
                .values(
                    id=uuid.uuid4(),
                    tenant_id=tenant_id,
                    user_id=user_id,
                    practice_set_id=None,
                    exercise_id=None,
                    cleared=True,
                )
                .on_conflict_do_update(
                    index_elements=["tenant_id", "user_id"],
                    set_={
                        "practice_set_id": None,
                        "exercise_id": None,
                        "cleared": True,
                        "updated_at": func.now(),
                    },
                )
            )
        await self._session.commit()

    async def save_report(
        self, material: ExerciseMaterial, reason: str, detail: str, key: str
    ) -> ExerciseReportView:
        statement = pg_insert(ExerciseReport).values(
            id=uuid.uuid4(),
            tenant_id=material.tenant_id,
            user_id=material.user_id,
            exercise_id=material.exercise_id,
            idempotency_key=key,
            reason=reason,
            detail=detail,
            status="open",
        )
        await self._session.execute(
            statement.on_conflict_do_nothing(
                index_elements=["tenant_id", "user_id", "exercise_id", "idempotency_key"]
            )
        )
        row = await self._session.scalar(
            select(ExerciseReport).where(
                ExerciseReport.tenant_id == material.tenant_id,
                ExerciseReport.user_id == material.user_id,
                ExerciseReport.exercise_id == material.exercise_id,
                ExerciseReport.idempotency_key == key,
            )
        )
        assert row is not None
        if row.reason != reason or row.detail != detail:
            raise AttemptConflict("idempotency key was used with a different report")
        await self._session.commit()
        return ExerciseReportView(id=row.id, exercise_id=row.exercise_id, created_at=row.created_at)

    async def get_memory_consent(self, tenant_id: UUID, user_id: UUID) -> bool:
        enabled = await self._session.scalar(
            select(StudyMemoryConsent.enabled).where(
                StudyMemoryConsent.tenant_id == tenant_id,
                StudyMemoryConsent.user_id == user_id,
            )
        )
        return bool(enabled)

    async def set_memory_consent(self, tenant_id: UUID, user_id: UUID, enabled: bool) -> None:
        statement = pg_insert(StudyMemoryConsent).values(
            id=uuid.uuid4(), tenant_id=tenant_id, user_id=user_id, enabled=enabled
        )
        await self._session.execute(
            statement.on_conflict_do_update(
                index_elements=["tenant_id", "user_id"],
                set_={"enabled": enabled, "updated_at": func.now()},
            )
        )
        await self._session.commit()
