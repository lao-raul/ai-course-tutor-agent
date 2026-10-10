"""Persistence port for learner-owned study state."""

from __future__ import annotations

from typing import Protocol
from uuid import UUID

from course_tutor_contracts import ExerciseReportView, StudySetProgressView
from course_tutor_practice.domain.attempts import AttemptRecord, Evaluation, ExerciseMaterial


class StudyRepository(Protocol):
    async def get_material(
        self, tenant_id: UUID, user_id: UUID, set_id: UUID, exercise_id: UUID
    ) -> ExerciseMaterial | None: ...

    async def find_material(
        self, tenant_id: UUID, user_id: UUID, exercise_id: UUID
    ) -> ExerciseMaterial | None: ...

    async def record_attempt(
        self,
        material: ExerciseMaterial,
        *,
        action: str,
        answer: str | bool | None,
        digest: str,
        idempotency_key: str,
        evaluation: Evaluation,
    ) -> AttemptRecord: ...

    async def list_progress(
        self, tenant_id: UUID, user_id: UUID
    ) -> tuple[StudySetProgressView, ...]: ...

    async def get_attempts(
        self, tenant_id: UUID, user_id: UUID, exercise_id: UUID
    ) -> tuple[AttemptRecord, ...]: ...

    async def get_cursor(self, tenant_id: UUID, user_id: UUID) -> tuple[UUID | None, bool]: ...

    async def reset_cursor(self, tenant_id: UUID, user_id: UUID, key: str) -> None: ...

    async def rebuild_progress(
        self, tenant_id: UUID, user_id: UUID, set_id: UUID
    ) -> StudySetProgressView | None: ...

    async def save_report(
        self, material: ExerciseMaterial, reason: str, detail: str, key: str
    ) -> ExerciseReportView: ...

    async def get_memory_consent(self, tenant_id: UUID, user_id: UUID) -> bool: ...

    async def set_memory_consent(self, tenant_id: UUID, user_id: UUID, enabled: bool) -> None: ...
