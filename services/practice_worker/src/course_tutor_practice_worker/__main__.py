"""Grounded generation worker entrypoint."""

from __future__ import annotations

import asyncio
import socket
from datetime import UTC, datetime, timedelta
from uuid import UUID

from sqlalchemy.ext.asyncio import async_sessionmaker, create_async_engine

from course_tutor_practice.adapters.agent_client import HttpAgentEvidenceProvider
from course_tutor_practice.adapters.inference import OpenAICompatiblePracticeInference
from course_tutor_practice.db.repository import SqlPracticeRepository
from course_tutor_practice.domain import GenerationRecord
from course_tutor_practice.generation.schemas import GenerationObjective
from course_tutor_practice_worker.evidence_first import EvidenceFirstGenerationExecutor
from course_tutor_practice_worker.worker import PracticeWorker
from course_tutor_shared import get_settings


async def main() -> None:
    settings = get_settings()
    engine = create_async_engine(
        settings.practice_postgres_dsn or settings.postgres_dsn,
        pool_pre_ping=True,
    )
    factory = async_sessionmaker(engine, expire_on_commit=False)
    evidence = HttpAgentEvidenceProvider(settings.agent_base_url)
    inference = OpenAICompatiblePracticeInference(
        settings.llm_base_url,
        settings.llm_chat_model,
        settings.llm_api_key.get_secret_value(),
    )

    async def read_objectives(
        generation: GenerationRecord,
    ) -> tuple[GenerationObjective, ...]:
        async with factory() as session:
            return await SqlPracticeRepository(session).list_recent_objectives(generation)

    executor = EvidenceFirstGenerationExecutor(evidence, inference, read_objectives)

    async def renew_lease(generation_id: UUID, worker_id: str, duration: timedelta) -> bool:
        async with factory() as session:
            return await SqlPracticeRepository(session).renew_generation_lease(
                generation_id, worker_id, datetime.now(UTC), duration
            )

    try:
        while True:
            async with factory() as session:
                worker = PracticeWorker(
                    SqlPracticeRepository(session),
                    executor,
                    worker_id=socket.gethostname(),
                    renew_lease=renew_lease,
                )
                processed = await worker.run_once()
            if not processed:
                await asyncio.sleep(2)
    finally:
        await evidence.aclose()
        await inference.aclose()
        await engine.dispose()


if __name__ == "__main__":
    asyncio.run(main())
