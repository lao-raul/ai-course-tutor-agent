from __future__ import annotations

import asyncio
import uuid
from datetime import UTC, datetime
from pathlib import Path

import pytest
from course_tutor_ingestion.embed_jobs import _process_embed_event
from course_tutor_ingestion.jobs import IngestionJob, run_pending_jobs
from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession, async_sessionmaker, create_async_engine

from course_tutor_api.auth import Principal
from course_tutor_api.db import (
    ContentVersion,
    Course,
    CourseRun,
    OutboxEvent,
    Programme,
    SourceDocument,
    SourceRoot,
    Tenant,
)
from course_tutor_api.routes.admin import (
    CourseRegistrationRequest,
    ProgrammeRegistrationRequest,
    publish_version,
    queue_ingestion,
    register_course,
    register_programme,
)
from course_tutor_contracts.enums import AccessLabel, ContentVersionStatus, EducationLevel, UserRole


class _Indexer:
    async def index_chunks(
        self, chunks: list[dict[str, object]], _version: dict[str, object]
    ) -> int:
        return len(chunks)


async def _scan(
    session: AsyncSession,
    *,
    tenant_id: uuid.UUID,
    course_id: uuid.UUID,
    source_root_id: uuid.UUID,
    root: Path,
) -> tuple[OutboxEvent, ContentVersion | None]:
    event = OutboxEvent(
        id=uuid.uuid4(),
        topic="ingestion.scan",
        idempotency_key=f"scan:test:{uuid.uuid4()}",
        payload={
            "tenant_id": str(tenant_id),
            "course_id": str(course_id),
            "source_root_id": str(source_root_id),
            "resolved_path": str(root),
        },
        attempts=0,
    )
    session.add(event)
    await session.commit()
    await IngestionJob(session, event).run()
    raw_version = event.payload.get("version_id")
    if not raw_version:
        return event, None
    version = await session.get(ContentVersion, uuid.UUID(raw_version))
    embed_result = await session.execute(
        select(OutboxEvent).where(OutboxEvent.idempotency_key == f"embed:{raw_version}")
    )
    embed_event = embed_result.scalar_one()
    await _process_embed_event(session, embed_event, _Indexer(), "test-embedding")
    embed_event.processed_at = event.processed_at
    await session.commit()
    return event, version


async def test_registration_is_separate_from_ingestion(
    db_session: AsyncSession, tmp_path: Path
) -> None:
    tenant_id = uuid.uuid4()
    db_session.add(Tenant(id=tenant_id, slug="registration", name="Registration"))
    await db_session.commit()
    principal = Principal(
        user_id=uuid.uuid4(),
        tenant_id=tenant_id,
        role=UserRole.INSTRUCTOR,
        access_label=AccessLabel.RESTRICTED,
        subject="registration-instructor",
    )
    programme = await register_programme(
        ProgrammeRegistrationRequest(code="MSC-AI", name="MSc AI"),
        db_session,
        principal,
    )
    course = await register_course(
        CourseRegistrationRequest(
            programme_id=programme.programme_id,
            code="COMP-REG",
            name="Registered Course",
            level=EducationLevel.POSTGRADUATE,
            run_key="2026-s1",
            source_path=str(tmp_path),
        ),
        db_session,
        principal,
    )
    assert (await db_session.execute(select(ContentVersion))).first() is None

    queued = await queue_ingestion(course.course_id, db_session, principal, None)
    assert queued.version_id is None
    assert await db_session.get(OutboxEvent, queued.job_id) is not None


async def test_add_edit_delete_rename_build_immutable_versions(
    db_session: AsyncSession, tmp_path: Path
) -> None:
    tenant_id, course_id, root_id = uuid.uuid4(), uuid.uuid4(), uuid.uuid4()
    db_session.add(Tenant(id=tenant_id, slug="test", name="Test"))
    await db_session.flush()
    programme = Programme(id=uuid.uuid4(), tenant_id=tenant_id, code="MSC-AI", name="MSc AI")
    db_session.add(programme)
    await db_session.flush()
    db_session.add(
        SourceRoot(
            id=root_id,
            tenant_id=tenant_id,
            absolute_path=str(tmp_path),
            last_scanned_at=None,
            last_snapshot_hash=None,
            scan_interval_seconds=900,
        )
    )
    await db_session.flush()
    db_session.add(
        Course(
            id=course_id,
            tenant_id=tenant_id,
            programme_id=programme.id,
            code="COMP-AI",
            name="AI",
            level=EducationLevel.POSTGRADUATE,
            source_root_id=root_id,
            teaching_policy={},
        )
    )
    await db_session.flush()
    db_session.add(
        CourseRun(
            id=uuid.uuid4(),
            course_id=course_id,
            run_key="2026-s1",
            source_root_id=root_id,
            active_content_version_id=None,
        )
    )
    await db_session.commit()
    principal = Principal(
        user_id=uuid.uuid4(),
        tenant_id=tenant_id,
        role=UserRole.INSTRUCTOR,
        access_label=AccessLabel.RESTRICTED,
        subject="test-instructor",
    )

    source = tmp_path / "lecture.md"
    source.write_text("# Search\nInitial lecture content.", encoding="utf-8")
    first_event, first = await _scan(
        db_session,
        tenant_id=tenant_id,
        course_id=course_id,
        source_root_id=root_id,
        root=tmp_path,
    )
    assert first is not None and first.status is ContentVersionStatus.READY
    await publish_version(course_id, first.id, db_session, principal)

    # Delivering the already committed event again is an idempotent no-op.
    await IngestionJob(db_session, first_event).run()

    (tmp_path / "exercise.txt").write_text("Question: explain search", encoding="utf-8")
    _, added = await _scan(
        db_session, tenant_id=tenant_id, course_id=course_id, source_root_id=root_id, root=tmp_path
    )
    source.write_text("# Search\nEdited lecture content.", encoding="utf-8")
    _, edited = await _scan(
        db_session, tenant_id=tenant_id, course_id=course_id, source_root_id=root_id, root=tmp_path
    )
    (tmp_path / "exercise.txt").unlink()
    _, deleted = await _scan(
        db_session, tenant_id=tenant_id, course_id=course_id, source_root_id=root_id, root=tmp_path
    )
    source.rename(tmp_path / "renamed.md")
    _, renamed = await _scan(
        db_session, tenant_id=tenant_id, course_id=course_id, source_root_id=root_id, root=tmp_path
    )

    versions = [first, added, edited, deleted, renamed]
    assert all(version is not None for version in versions)
    assert [version.sequence for version in versions if version] == [1, 2, 3, 4, 5]
    assert (await db_session.get(Course, course_id)).active_content_version_id == first.id  # type: ignore[union-attr]
    latest_sources = await db_session.execute(
        select(SourceDocument.relative_path).where(SourceDocument.version_id == renamed.id)  # type: ignore[union-attr]
    )
    assert set(latest_sources.scalars()) == {"renamed.md"}

    # No source change creates no sixth content version.
    unchanged_event, unchanged = await _scan(
        db_session,
        tenant_id=tenant_id,
        course_id=course_id,
        source_root_id=root_id,
        root=tmp_path,
    )
    assert unchanged is None
    assert unchanged_event.payload["stats"]["no_change"] is True


async def test_validation_failures_dead_letter(db_session: AsyncSession, tmp_path: Path) -> None:
    tenant_id, course_id, root_id = uuid.uuid4(), uuid.uuid4(), uuid.uuid4()
    db_session.add(Tenant(id=tenant_id, slug="dead-letter", name="Dead Letter"))
    await db_session.flush()
    programme = Programme(id=uuid.uuid4(), tenant_id=tenant_id, code="FAIL-P", name="Failure")
    db_session.add(programme)
    await db_session.flush()
    db_session.add(
        SourceRoot(
            id=root_id,
            tenant_id=tenant_id,
            absolute_path=str(tmp_path / "missing"),
            last_scanned_at=None,
            last_snapshot_hash=None,
            scan_interval_seconds=900,
        )
    )
    await db_session.flush()
    db_session.add(
        Course(
            id=course_id,
            tenant_id=tenant_id,
            programme_id=programme.id,
            code="FAIL",
            name="Failure",
            level=EducationLevel.POSTGRADUATE,
            source_root_id=root_id,
            teaching_policy={},
        )
    )
    await db_session.flush()
    db_session.add(
        CourseRun(
            id=uuid.uuid4(),
            course_id=course_id,
            run_key="2026-s1",
            source_root_id=root_id,
            active_content_version_id=None,
        )
    )
    event = OutboxEvent(
        id=uuid.uuid4(),
        topic="ingestion.scan",
        idempotency_key=f"scan:failure:{uuid.uuid4()}",
        payload={
            "tenant_id": str(tenant_id),
            "course_id": str(course_id),
            "source_root_id": str(root_id),
            "resolved_path": str(tmp_path / "missing"),
        },
        attempts=0,
    )
    db_session.add(event)
    await db_session.commit()

    assert await run_pending_jobs(db_session, max_batch=2, max_attempts=2) == 2
    await db_session.refresh(event)
    assert event.attempts == 2
    assert event.dead_lettered_at is not None
    assert "does not exist" in (event.last_error or "")


async def test_two_workers_cannot_process_same_event_concurrently(
    db_session: AsyncSession, monkeypatch: pytest.MonkeyPatch
) -> None:
    event = OutboxEvent(
        id=uuid.uuid4(),
        topic="ingestion.scan",
        idempotency_key=f"scan:locking:{uuid.uuid4()}",
        payload={"course_id": str(uuid.uuid4())},
        attempts=0,
    )
    db_session.add(event)
    await db_session.commit()

    entered = asyncio.Event()
    release = asyncio.Event()

    class _BlockingJob:
        def __init__(
            self,
            session: AsyncSession,
            event: OutboxEvent,
            _object_store: object = None,
        ) -> None:
            self.session = session
            self.event = event

        async def run(self) -> None:
            entered.set()
            await release.wait()
            self.event.processed_at = datetime.now(UTC).replace(tzinfo=None)
            await self.session.commit()

    monkeypatch.setattr("course_tutor_ingestion.jobs.IngestionJob", _BlockingJob)
    dsn = db_session.bind.url.render_as_string(hide_password=False)  # type: ignore[union-attr]
    engine = create_async_engine(dsn)
    maker = async_sessionmaker(engine, expire_on_commit=False)
    async with maker() as first_session, maker() as second_session:
        first = asyncio.create_task(run_pending_jobs(first_session, max_batch=1))
        await asyncio.wait_for(entered.wait(), timeout=10)
        second_count = await run_pending_jobs(second_session, max_batch=1)
        release.set()
        first_count = await first
    await engine.dispose()

    assert first_count == 1
    assert second_count == 0
