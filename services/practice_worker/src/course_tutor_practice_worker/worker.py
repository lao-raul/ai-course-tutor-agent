"""Lease-safe, at-least-once generation outbox consumer."""

from __future__ import annotations

from datetime import UTC, datetime, timedelta
from typing import Protocol

from course_tutor_contracts import ExerciseDraft, GenerationStatus
from course_tutor_practice.domain import GenerationRecord
from course_tutor_practice.ports import PracticeRepository


class GenerationExecutor(Protocol):
    async def generate(self, job: GenerationRecord) -> tuple[ExerciseDraft, ...]: ...


class RetryableGenerationError(RuntimeError):
    pass


class PracticeWorker:
    def __init__(
        self,
        repository: PracticeRepository,
        executor: GenerationExecutor,
        *,
        worker_id: str,
        lease_duration: timedelta = timedelta(seconds=30),
        max_attempts: int = 5,
    ) -> None:
        self._repository = repository
        self._executor = executor
        self._worker_id = worker_id
        self._lease_duration = lease_duration
        self._max_attempts = max_attempts

    async def run_once(self, now: datetime | None = None) -> bool:
        job = await self._repository.claim_next_generation(
            self._worker_id,
            now or datetime.now(UTC),
            self._lease_duration,
        )
        if job is None:
            return False
        try:
            await self._repository.transition_generation(job.id, GenerationStatus.GENERATING)
            drafts = await self._executor.generate(job)
            if len(drafts) != job.requested_count:
                raise ValueError("executor returned a different question count")
            await self._repository.transition_generation(job.id, GenerationStatus.VALIDATING)
            await self._repository.complete_generation(
                job.id,
                drafts,
                seed=0,
                prompt_version="task-19-port-v1",
                model_version="provider-supplied",
                validator_version="task-19-schema-v1",
            )
        except RetryableGenerationError as exc:
            await self._repository.retry_or_fail_generation(
                job.id,
                "dependency_unavailable",
                str(exc),
                retryable=True,
                max_attempts=self._max_attempts,
            )
        except Exception as exc:
            await self._repository.retry_or_fail_generation(
                job.id,
                "generation_failed",
                str(exc),
                retryable=False,
                max_attempts=self._max_attempts,
            )
        return True
