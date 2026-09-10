from __future__ import annotations

from course_tutor_ingestion.jobs import run_pending_jobs
from sqlalchemy.dialects import postgresql


class _Result:
    def scalar_one_or_none(self) -> None:
        return None


class _Session:
    statement = None

    async def execute(self, statement: object) -> _Result:
        self.statement = statement
        return _Result()


async def test_scan_worker_claims_with_skip_locked() -> None:
    session = _Session()
    assert await run_pending_jobs(session, max_batch=1) == 0  # type: ignore[arg-type]
    sql = str(session.statement.compile(dialect=postgresql.dialect()))
    assert "FOR UPDATE SKIP LOCKED" in sql
