"""Worker entrypoint; TASK-20 supplies the grounded generation executor."""

from __future__ import annotations

import asyncio
import socket

from sqlalchemy.ext.asyncio import async_sessionmaker, create_async_engine

from course_tutor_practice.db.repository import SqlPracticeRepository
from course_tutor_practice_worker.worker import PracticeWorker, RetryableGenerationError
from course_tutor_shared import get_settings


class PendingTask20Executor:
    async def generate(self, _job):  # type: ignore[no-untyped-def]
        raise RetryableGenerationError("grounded generation executor is pending TASK-20")


async def main() -> None:
    settings = get_settings()
    engine = create_async_engine(
        settings.practice_postgres_dsn or settings.postgres_dsn,
        pool_pre_ping=True,
    )
    factory = async_sessionmaker(engine, expire_on_commit=False)
    try:
        while True:
            async with factory() as session:
                worker = PracticeWorker(
                    SqlPracticeRepository(session),
                    PendingTask20Executor(),
                    worker_id=socket.gethostname(),
                )
                processed = await worker.run_once()
            if not processed:
                await asyncio.sleep(2)
    finally:
        await engine.dispose()


if __name__ == "__main__":
    asyncio.run(main())
