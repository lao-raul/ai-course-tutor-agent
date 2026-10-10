"""Grounded generation worker entrypoint."""

from __future__ import annotations

import asyncio
import socket

from sqlalchemy.ext.asyncio import async_sessionmaker, create_async_engine

from course_tutor_practice.adapters.agent_client import HttpAgentEvidenceProvider
from course_tutor_practice.adapters.inference import OpenAICompatiblePracticeInference
from course_tutor_practice.db.repository import SqlPracticeRepository
from course_tutor_practice_worker.grounded import GroundedGenerationExecutor
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
    executor = GroundedGenerationExecutor(evidence, inference)
    try:
        while True:
            async with factory() as session:
                worker = PracticeWorker(
                    SqlPracticeRepository(session),
                    executor,
                    worker_id=socket.gethostname(),
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
