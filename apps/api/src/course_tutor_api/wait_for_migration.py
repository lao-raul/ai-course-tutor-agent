"""Init-container gate that waits for the release migration Job to finish."""

from __future__ import annotations

import asyncio
import os
import time

import asyncpg


async def wait() -> None:
    dsn = os.environ["POSTGRES_DSN"].replace("postgresql+asyncpg://", "postgresql://")
    expected = os.environ.get("EXPECTED_ALEMBIC_REVISION", "f31b8d02c913")
    deadline = time.monotonic() + float(os.environ.get("MIGRATION_WAIT_SECONDS", "180"))
    last_error = "migration has not started"
    while time.monotonic() < deadline:
        try:
            connection = await asyncpg.connect(dsn)
            try:
                revision = await connection.fetchval("SELECT version_num FROM alembic_version")
                if revision == expected:
                    return
                last_error = f"expected migration {expected}, found {revision}"
            finally:
                await connection.close()
        except (OSError, asyncpg.PostgresError) as exc:
            last_error = str(exc)
        await asyncio.sleep(2)
    raise TimeoutError(last_error)


if __name__ == "__main__":
    asyncio.run(wait())
