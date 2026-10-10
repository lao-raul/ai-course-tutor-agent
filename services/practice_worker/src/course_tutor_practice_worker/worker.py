"""Lease-safe, at-least-once generation outbox consumer."""

from __future__ import annotations

from datetime import UTC, datetime, timedelta
from typing import Protocol

from course_tutor_contracts import GenerationStatus
from course_tutor_practice.domain import GenerationRecord
from course_tutor_practice.generation.errors import GenerationFailure
from course_tutor_practice.generation.schemas import GenerationContext, GenerationOutcome
from course_tutor_practice.ports import PracticeRepository


class GenerationExecutor(Protocol):
    async def retrieve(self, job: GenerationRecord) -> GenerationContext: ...

    async def generate(
        self, job: GenerationRecord, context: GenerationContext
    ) -> GenerationOutcome: ...


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
            context = await self._executor.retrieve(job)
            await self._repository.transition_generation(job.id, GenerationStatus.GENERATING)
            outcome = await self._executor.generate(job, context)
            if len(outcome.drafts) != job.requested_count:
                raise GenerationFailure("count_mismatch")
            await self._repository.transition_generation(job.id, GenerationStatus.VALIDATING)
            await self._repository.complete_generation(
                job.id,
                outcome.drafts,
                seed=outcome.seed,
                prompt_version=outcome.prompt_version,
                model_version=outcome.model_version,
                validator_version=outcome.validator_version,
                retrieval_trace_id=outcome.retrieval_trace_id,
            )
        except GenerationFailure as exc:
            await self._repository.retry_or_fail_generation(
                job.id,
                exc.code,
                exc.code,
                retryable=exc.retryable,
                max_attempts=self._max_attempts,
            )
        except RetryableGenerationError:
            await self._repository.retry_or_fail_generation(
                job.id,
                "dependency_unavailable",
                "dependency_unavailable",
                retryable=True,
                max_attempts=self._max_attempts,
            )
        except Exception:
            await self._repository.retry_or_fail_generation(
                job.id,
                "generation_failed",
                "unexpected generation failure",
                retryable=False,
                max_attempts=self._max_attempts,
            )
        return True
