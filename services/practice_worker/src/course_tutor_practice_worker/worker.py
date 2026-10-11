"""Lease-safe, at-least-once generation outbox consumer."""

from __future__ import annotations

import asyncio
from collections.abc import Awaitable, Callable
from contextlib import suppress
from datetime import UTC, datetime, timedelta
from typing import Protocol
from uuid import UUID

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


class LostGenerationLease(RuntimeError):
    """A different consumer owns the job; this worker must not mutate it."""


class PracticeWorker:
    def __init__(
        self,
        repository: PracticeRepository,
        executor: GenerationExecutor,
        *,
        worker_id: str,
        lease_duration: timedelta = timedelta(seconds=30),
        max_attempts: int = 5,
        renew_lease: Callable[[UUID, str, timedelta], Awaitable[bool]] | None = None,
    ) -> None:
        self._repository = repository
        self._executor = executor
        self._worker_id = worker_id
        self._lease_duration = lease_duration
        self._max_attempts = max_attempts
        self._renew_lease = renew_lease

    async def _owns_lease(self, generation_id: UUID) -> bool:
        if self._renew_lease is None:
            return True
        return await self._renew_lease(generation_id, self._worker_id, self._lease_duration)

    async def _heartbeat(self, generation_id: UUID, owner: asyncio.Task[object]) -> None:
        interval = max(self._lease_duration.total_seconds() / 3, 0.05)
        while True:
            await asyncio.sleep(interval)
            try:
                owned = await self._owns_lease(generation_id)
            except Exception:
                owned = False
            if not owned:
                owner.cancel()
                return

    async def run_once(self, now: datetime | None = None) -> bool:
        job = await self._repository.claim_next_generation(
            self._worker_id,
            now or datetime.now(UTC),
            self._lease_duration,
        )
        if job is None:
            return False
        heartbeat: asyncio.Task[None] | None = None
        if self._renew_lease is not None:
            owner = asyncio.current_task()
            assert owner is not None
            heartbeat = asyncio.create_task(self._heartbeat(job.id, owner))
        try:
            context = await self._executor.retrieve(job)
            if not await self._owns_lease(job.id):
                raise LostGenerationLease
            await self._repository.transition_generation(job.id, GenerationStatus.GENERATING)
            outcome = await self._executor.generate(job, context)
            if len(outcome.drafts) != job.requested_count:
                raise GenerationFailure("count_mismatch")
            if not await self._owns_lease(job.id):
                raise LostGenerationLease
            await self._repository.transition_generation(job.id, GenerationStatus.VALIDATING)
            if not await self._owns_lease(job.id):
                raise LostGenerationLease
            await self._repository.complete_generation(
                job.id,
                outcome.drafts,
                seed=outcome.seed,
                prompt_version=outcome.prompt_version,
                model_version=outcome.model_version,
                validator_version=outcome.validator_version,
                retrieval_trace_id=outcome.retrieval_trace_id,
                objectives=outcome.objectives,
            )
        except LostGenerationLease:
            pass
        except GenerationFailure as exc:
            if await self._owns_lease(job.id):
                await self._repository.retry_or_fail_generation(
                    job.id,
                    exc.code,
                    exc.code,
                    retryable=exc.retryable,
                    max_attempts=self._max_attempts,
                )
        except RetryableGenerationError:
            if await self._owns_lease(job.id):
                await self._repository.retry_or_fail_generation(
                    job.id,
                    "dependency_unavailable",
                    "dependency_unavailable",
                    retryable=True,
                    max_attempts=self._max_attempts,
                )
        except Exception:
            if await self._owns_lease(job.id):
                await self._repository.retry_or_fail_generation(
                    job.id,
                    "generation_failed",
                    "unexpected generation failure",
                    retryable=False,
                    max_attempts=self._max_attempts,
                )
        finally:
            if heartbeat is not None:
                heartbeat.cancel()
                with suppress(asyncio.CancelledError):
                    await heartbeat
        return True
