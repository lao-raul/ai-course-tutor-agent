"""Fail-closed PostgreSQL helpers for destructive integration tests."""

from __future__ import annotations

from urllib.parse import urlparse

from sqlalchemy import text
from sqlalchemy.ext.asyncio import AsyncEngine

SAFE_DATABASE_PREFIX = "course_tutor_test_"
MARKER_TABLE = "_course_tutor_test_marker"


def database_name_from_dsn(dsn: str) -> str:
    return urlparse(dsn.replace("+asyncpg", "")).path.removeprefix("/")


def assert_safe_test_database_dsn(dsn: str) -> str:
    database = database_name_from_dsn(dsn)
    if not database.startswith(SAFE_DATABASE_PREFIX):
        raise RuntimeError(
            f"refusing destructive test operation on database {database!r}; "
            f"name must start with {SAFE_DATABASE_PREFIX!r}"
        )
    return database


async def reset_test_schema(engine: AsyncEngine, dsn: str) -> None:
    """Reset only an empty or previously marked dedicated test database."""
    database = assert_safe_test_database_dsn(dsn)
    async with engine.begin() as connection:
        relation_count = await connection.scalar(
            text(
                "SELECT count(*) FROM pg_class c "
                "JOIN pg_namespace n ON n.oid = c.relnamespace "
                "WHERE n.nspname = 'public' AND c.relkind IN ('r', 'p', 'v', 'm')"
            )
        )
        marker_exists = await connection.scalar(
            text("SELECT to_regclass(:marker) IS NOT NULL"),
            {"marker": f"public.{MARKER_TABLE}"},
        )
        if marker_exists:
            marker = await connection.scalar(
                text(f"SELECT database_name FROM {MARKER_TABLE} LIMIT 1")
            )
            if marker != database:
                raise RuntimeError("refusing cleanup: dedicated test database marker is invalid")
        elif relation_count:
            raise RuntimeError("refusing cleanup: non-empty test database has no safety marker")

        await connection.execute(text("DROP SCHEMA IF EXISTS public CASCADE"))
        await connection.execute(text("CREATE SCHEMA public"))
        await connection.execute(
            text(
                f"CREATE TABLE {MARKER_TABLE} "
                "(database_name text PRIMARY KEY, created_at timestamptz DEFAULT now())"
            )
        )
        await connection.execute(
            text(f"INSERT INTO {MARKER_TABLE} (database_name) VALUES (:database_name)"),
            {"database_name": database},
        )


async def assert_test_marker(engine: AsyncEngine, dsn: str) -> None:
    database = assert_safe_test_database_dsn(dsn)
    async with engine.connect() as connection:
        marker = await connection.scalar(text(f"SELECT database_name FROM {MARKER_TABLE} LIMIT 1"))
    if marker != database:
        raise RuntimeError("refusing cleanup: dedicated test database marker is missing")
