"""Repository contract for the separately owned Practice schema."""

from __future__ import annotations

from datetime import datetime, timedelta
from typing import Protocol
from uuid import UUID

from course_tutor_contracts import ExerciseDraft, GenerationStatus
from course_tutor_practice.domain import GenerationRecord, PracticeSetRecord, StudyPlanRecord


class PracticeRepository(Protocol):
    async def get_study_plan(
        self, tenant_id: UUID, book_id: UUID, content_version_id: UUID
    ) -> StudyPlanRecord | None: ...

    async def find_study_plan_by_course(
        self, tenant_id: UUID, course_id: UUID
    ) -> StudyPlanRecord | None: ...

    async def save_study_plan(self, plan: StudyPlanRecord) -> StudyPlanRecord: ...

    async def submit_generation(
        self, generation: GenerationRecord
    ) -> tuple[GenerationRecord, bool]: ...

    async def get_generation(
        self, tenant_id: UUID, user_id: UUID, generation_id: UUID
    ) -> GenerationRecord | None: ...

    async def cancel_generation(
        self, tenant_id: UUID, user_id: UUID, generation_id: UUID
    ) -> GenerationRecord | None: ...

    async def get_practice_set(
        self, tenant_id: UUID, user_id: UUID, set_id: UUID
    ) -> PracticeSetRecord | None: ...

    async def claim_next_generation(
        self, worker_id: str, now: datetime, lease_duration: timedelta
    ) -> GenerationRecord | None: ...

    async def transition_generation(
        self, generation_id: UUID, target: GenerationStatus
    ) -> GenerationRecord: ...

    async def retry_or_fail_generation(
        self,
        generation_id: UUID,
        error_code: str,
        detail: str,
        *,
        retryable: bool,
        max_attempts: int,
    ) -> GenerationRecord: ...

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
    ) -> PracticeSetRecord: ...
