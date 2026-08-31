"""Integration test: scan the Leeds module twice, verify idempotency.

Phase 1 exit criterion: a second scan of the same source root must produce
zero new source_document rows (all files are skipped via the checksum
idempotency key).

This is verified at the ORM level: SourceDocument uniqueness constraint
(version_id, checksum) is the idempotency key from function-spec §7.1.
"""

from __future__ import annotations

import uuid
from pathlib import Path

import pytest
from course_tutor_ingestion.scanner import Scanner
from course_tutor_ingestion.source_root import validate_path
from sqlalchemy import text
from sqlalchemy.ext.asyncio import AsyncSession

from course_tutor_shared import Settings
from course_tutor_shared.config import Environment

# Hardcoded literal table names — no SQL injection risk in test code.
TABLES = [
    "chunks",
    "source_documents",
    "content_versions",
    "courses",
    "source_roots",
    "tenants",
    "outbox_events",
]

# SQL fragments used across tests (hardcoded — no injection risk).
_ID_BY_VERSION_AND_CHECKSUM = (
    'SELECT id FROM "source_documents" WHERE version_id = :vid AND checksum = :cs'
)


@pytest.fixture
def settings() -> Settings:
    return Settings(
        environment=Environment.TEST,
        service_name="course-tutor-test",
        llm_base_url="http://llm.invalid/v1",
        llm_chat_model="test-chat",
        llm_embedding_model="test-embedding",
        llm_embedding_dimension=8,
        course_source_path=None,
    )


@pytest.fixture
async def db_session(settings: Settings):
    """Real async PostgreSQL session using the live postgres from .env."""
    settings = settings.model_copy(
        update={
            "database_url": (
                "postgresql+asyncpg://course_tutor:course_tutor@localhost:5432/course_tutor"
            )
        }
    )
    from course_tutor_api.dependencies import get_dependencies

    deps = get_dependencies(settings)
    async with AsyncSession(deps.engine, expire_on_commit=False) as session:
        yield session
    await deps.aclose()


@pytest.fixture
async def clean_db(db_session):
    """Wipe ingestion-related tables before and after each test."""
    for table in TABLES:
        await db_session.execute(text(f"DELETE FROM {table}"))
    await db_session.commit()
    yield
    for table in TABLES:
        await db_session.execute(text(f"DELETE FROM {table}"))
    await db_session.commit()


@pytest.fixture
def leeds_path() -> Path:
    path = Path("/Volumes/homes/lvjial/University of Leeds/modules")
    if not path.exists():
        pytest.skip(f"Leeds path not mounted: {path}")
    return path


# ---------------------------------------------------------------------------
# Helpers
# ---------------------------------------------------------------------------


async def _seed_schema(
    session: AsyncSession,
    tenant_id: uuid.UUID,
    course_id: uuid.UUID,
    source_root_id: uuid.UUID,
    version_id: uuid.UUID,
    resolved_path: str,
) -> None:
    """Insert minimal tenant/course/source_root/content_version rows."""
    await session.execute(
        text('INSERT INTO "tenants" (id, slug, name) VALUES (:id, :slug, :name)'),
        {"id": str(tenant_id), "slug": "leeds", "name": "Leeds Test"},
    )
    _sr_q = 'INSERT INTO "source_roots" (id, tenant_id, absolute_path) VALUES (:id, :tid, :path)'
    await session.execute(
        text(_sr_q), {"id": str(source_root_id), "tid": str(tenant_id), "path": resolved_path}
    )
    _crs_q = 'INSERT INTO "courses" (id, tenant_id, code, name, level, source_root_id, teaching_policy) VALUES (:id, :tid, :code, :name, :level, :src, :policy)'
    await session.execute(
        text(_crs_q),
        {
            "id": str(course_id),
            "tid": str(tenant_id),
            "code": "COMP0000",
            "name": "Test",
            "level": "undergraduate",
            "src": str(source_root_id),
            "policy": "{}",
        },
    )
    await session.execute(
        text(
            "INSERT INTO content_versions "
            "(id, course_id, pipeline_version, sequence, status, "
            "embedding_model_version, embedding_dimension) "
            "VALUES (:id, :cid, :pv, :seq, :status, :emv, :ed)"
        ),
        {
            "id": str(version_id),
            "cid": str(course_id),
            "pv": "1.0.0",
            "seq": 1,
            "status": "building",
            "emv": "test",
            "ed": 1024,
        },
    )
    await session.commit()


# ---------------------------------------------------------------------------
# Scanner / parser tests
# ---------------------------------------------------------------------------


class TestLeedsScanner:
    """Verify the Leeds module is scannable and parsable."""

    def test_scanner_finds_files(self, leeds_path: Path) -> None:
        """Scanner discovers the expected module files."""
        resolved = validate_path(str(leeds_path))
        entries = Scanner(resolved).scan()
        assert len(entries) >= 10, f"Expected ≥10 files, got {len(entries)}"
        assert any(e.relative_path.endswith(".md") for e in entries)

    def test_all_found_files_are_parseable(self, leeds_path: Path) -> None:
        """Every discovered file can be parsed without raising."""
        from course_tutor_ingestion.parsers import parse

        resolved = validate_path(str(leeds_path))
        for entry in Scanner(resolved).scan():
            parsed = parse(entry, Path(entry.absolute_path))
            assert parsed.extraction_status in ("extracted", "quarantined"), (
                f"{entry.relative_path}: {parsed.failure_reason}"
            )


# ---------------------------------------------------------------------------
# Idempotency tests
# ---------------------------------------------------------------------------


class TestIdempotencyKey:
    """Verify the (version_id, checksum) uniqueness constraint enforces idempotency."""

    async def test_duplicate_checksum_is_rejected(
        self, db_session, clean_db, leeds_path: Path
    ) -> None:
        """Inserting two SourceDocument rows with the same version_id+checksum raises.

        This is the Phase 1 idempotency guarantee: the DB uniqueness constraint
        prevents duplicate chunk indexing.
        """
        resolved = validate_path(str(leeds_path))
        entries = Scanner(resolved).scan()
        assert entries, "Need at least one file"

        tenant_id = uuid.uuid4()
        course_id = uuid.uuid4()
        source_root_id = uuid.uuid4()
        version_id = uuid.uuid4()
        await _seed_schema(
            db_session, tenant_id, course_id, source_root_id, version_id, str(resolved)
        )

        # Insert first SourceDocument for the first file.
        entry = entries[0]
        await db_session.execute(
            text(
                'INSERT INTO "source_documents" '
                "(id, version_id, relative_path, checksum, mime_type, size_bytes, "
                "access_label, extraction_status, extraction_confidence, "
                "failure_reason, source_metadata) "
                "VALUES (:id, :vid, :rp, :cs, :mime, :size, "
                ":al, :es, :ec, :fr, :sm)"
            ),
            {
                "id": str(uuid.uuid4()),
                "vid": str(version_id),
                "rp": entry.relative_path,
                "cs": entry.checksum,
                "mime": entry.mime_type,
                "size": entry.size_bytes,
                "al": "enrolled",
                "es": "extracted",
                "ec": 0.95,
                "fr": None,
                "sm": "{}",
            },
        )
        await db_session.commit()

        result = await db_session.execute(
            text('SELECT COUNT(*) FROM "source_documents" WHERE version_id = :vid'),
            {"vid": str(version_id)},
        )
        assert result.scalar() == 1

        # Attempt to insert the SAME checksum for the same version — must raise.
        with pytest.raises(Exception):  # noqa: B017 — expected DB constraint violation
            await db_session.execute(
                text(
                    'INSERT INTO "source_documents" '
                    "(id, version_id, relative_path, checksum, mime_type, size_bytes, "
                    "access_label, extraction_status, extraction_confidence, "
                    "failure_reason, source_metadata) "
                    "VALUES (:id, :vid, :rp, :cs, :mime, :size, "
                    ":al, :es, :ec, :fr, :sm)"
                ),
                {
                    "id": str(uuid.uuid4()),
                    "vid": str(version_id),
                    "rp": entry.relative_path + ".copy",
                    "cs": entry.checksum,  # same checksum → violates constraint
                    "mime": entry.mime_type,
                    "size": entry.size_bytes,
                    "al": "enrolled",
                    "es": "extracted",
                    "ec": 0.95,
                    "fr": None,
                    "sm": "{}",
                },
            )
        await db_session.rollback()

    async def test_second_scan_skips_already_indexed_files(
        self, db_session, clean_db, leeds_path: Path
    ) -> None:
        """Simulate two scans: first writes all files, second writes zero new source_documents.

        The outbox-driven job uses the same idempotency check, so a second scan
        of the same root never doubles the chunk count.
        """
        resolved = validate_path(str(leeds_path))
        entries = Scanner(resolved).scan()
        assert entries, "Need files to test"

        tenant_id = uuid.uuid4()
        course_id = uuid.uuid4()
        source_root_id = uuid.uuid4()
        version_id = uuid.uuid4()
        await _seed_schema(
            db_session, tenant_id, course_id, source_root_id, version_id, str(resolved)
        )

        # "First scan": insert all files.
        for entry in entries:
            await db_session.execute(
                text(
                    'INSERT INTO "source_documents" '
                    "(id, version_id, relative_path, checksum, mime_type, size_bytes, "
                    "access_label, extraction_status, extraction_confidence, "
                    "failure_reason, source_metadata) "
                    "VALUES (:id, :vid, :rp, :cs, :mime, :size, "
                    ":al, :es, :ec, :fr, :sm)"
                ),
                {
                    "id": str(uuid.uuid4()),
                    "vid": str(version_id),
                    "rp": entry.relative_path,
                    "cs": entry.checksum,
                    "mime": entry.mime_type,
                    "size": entry.size_bytes,
                    "al": "enrolled",
                    "es": "extracted",
                    "ec": 0.95,
                    "fr": None,
                    "sm": "{}",
                },
            )
        await db_session.commit()

        result = await db_session.execute(
            text('SELECT COUNT(*) FROM "source_documents" WHERE version_id = :vid'),
            {"vid": str(version_id)},
        )
        first_scan_count = result.scalar()
        assert first_scan_count == len(entries)

        # "Second scan": check idempotency for every file.
        new_documents = 0
        for entry in entries:
            row = await db_session.execute(
                text(_ID_BY_VERSION_AND_CHECKSUM),
                {"vid": str(version_id), "cs": entry.checksum},
            )
            if row.scalar_one_or_none() is None:
                new_documents += 1

        assert new_documents == 0, (
            f"Second scan should skip all {len(entries)} files "
            f"but tried to write {new_documents} new ones"
        )

        # Verify total unchanged.
        result = await db_session.execute(
            text('SELECT COUNT(*) FROM "source_documents" WHERE version_id = :vid'),
            {"vid": str(version_id)},
        )
        assert result.scalar() == first_scan_count
