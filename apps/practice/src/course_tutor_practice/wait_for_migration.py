"""Wait until the independently owned Practice schema reaches the chart revision."""

from __future__ import annotations

import asyncio
import os
import sys
import time

from sqlalchemy import text
from sqlalchemy.ext.asyncio import create_async_engine

from course_tutor_shared import get_settings


async def main() -> None:
    settings = get_settings()
    expected = os.environ["EXPECTED_PRACTICE_ALEMBIC_REVISION"]
    deadline = time.monotonic() + 300
    once = "--once" in sys.argv[1:]
    last_error = "schema not at expected revision"
    engine = create_async_engine(settings.practice_postgres_dsn or settings.postgres_dsn)
    try:
        while True:
            try:
                async with engine.connect() as connection:
                    actual = await connection.scalar(
                        text("SELECT version_num FROM practice_alembic_version")
                    )
                if actual == expected:
                    return
            except Exception as exc:  # migration/database can be temporarily unavailable
                last_error = type(exc).__name__
            if once or time.monotonic() >= deadline:
                raise TimeoutError(f"Practice migration did not reach {expected}: {last_error}")
            await asyncio.sleep(3)
    finally:
        await engine.dispose()


if __name__ == "__main__":
    asyncio.run(main())
