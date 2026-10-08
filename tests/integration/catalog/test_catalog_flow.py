from __future__ import annotations

import uuid
from pathlib import Path

import pytest
from course_tutor_ingestion.catalog_jobs import run_pending_catalog_jobs
from fastapi import HTTPException
from sqlalchemy import func, select
from sqlalchemy.ext.asyncio import AsyncSession

from course_tutor_api.auth import Principal
from course_tutor_api.course_access import principal_can_access_course_record
from course_tutor_api.db import (
    Book,
    BookContentBinding,
    CatalogImportBatch,
    CatalogImportCandidate,
    ContentVersion,
    ContentVersionSource,
    Course,
    CourseRun,
    OutboxEvent,
    SourceDocument,
    SourceRoot,
    Tenant,
)
from course_tutor_api.routes.admin import publish_version
from course_tutor_api.routes.catalog import get_catalog_book, search_catalog_books
from course_tutor_api.routes.catalog_admin import (
    approve_catalog_import_candidate,
    list_catalog_import_candidates,
    update_catalog_import_candidate,
)
from course_tutor_contracts import CatalogCandidateUpdateRequest
from course_tutor_contracts.enums import (
    AccessLabel,
    CatalogCandidateStatus,
    ContentVersionStatus,
    CourseAccessPolicy,
    EducationLevel,
    ExtractionStatus,
    UserRole,
)


def _pdf(root: Path) -> Path:
    path = (
        root
        / "小学"
        / "英语"
        / "外研社版（三年级起点）（主编：陈琳）"  # noqa: RUF001
        / "义务教育教科书·英语三年级上册.pdf"
    )
    path.parent.mkdir(parents=True)
    path.write_bytes(b"%PDF-test-catalog")
    return path


async def _queue_scan(
    session: AsyncSession, tenant_id: uuid.UUID, source_root_id: uuid.UUID
) -> OutboxEvent:
    event = OutboxEvent(
        id=uuid.uuid4(),
        topic="catalog.scan",
        idempotency_key=f"catalog-test:{uuid.uuid4()}",
        payload={
            "tenant_id": str(tenant_id),
            "source_root_id": str(source_root_id),
            "prefix": "小学/英语",
            "series_contains": "外研社",
            "selection": {"prefix": "小学/英语", "series_contains": "外研社"},
        },
        attempts=0,
    )
    session.add(event)
    await session.commit()
    assert await run_pending_catalog_jobs(session) == 1
    await session.refresh(event)
    return event


async def test_catalog_scan_approval_publication_and_tenant_access(
    db_session: AsyncSession, tmp_path: Path
) -> None:
    _pdf(tmp_path)
    tenant_id = uuid.uuid4()
    db_session.add(Tenant(id=tenant_id, slug=f"catalog-{tenant_id}", name="Catalog"))
    await db_session.flush()
    source_root = SourceRoot(
        id=uuid.uuid4(),
        tenant_id=tenant_id,
        absolute_path=str(tmp_path),
        scan_interval_seconds=900,
        automatic_ingestion_enabled=False,
    )
    db_session.add(source_root)
    await db_session.commit()

    first = await _queue_scan(db_session, tenant_id, source_root.id)
    second = await _queue_scan(db_session, tenant_id, source_root.id)
    assert first.payload["batch_id"] == second.payload["batch_id"]
    assert await db_session.scalar(select(func.count(CatalogImportBatch.id))) == 1

    candidate = (await db_session.execute(select(CatalogImportCandidate))).scalar_one()
    assert candidate.status is CatalogCandidateStatus.STAGED
    admin = Principal(
        user_id=uuid.uuid4(),
        tenant_id=tenant_id,
        role=UserRole.PLATFORM_ADMIN,
        access_label=AccessLabel.RESTRICTED,
        subject="catalog-admin",
    )
    views = await list_catalog_import_candidates(first.id, db_session, admin)
    assert len(views) == 1
    assert "relative_path" not in views[0].model_dump()
    assert str(tmp_path) not in views[0].model_dump_json()

    candidate.status = CatalogCandidateStatus.NEEDS_REVIEW
    candidate.issues = ["publisher_requires_confirmation"]
    await db_session.commit()
    with pytest.raises(HTTPException, match="requires review"):
        await approve_catalog_import_candidate(first.id, candidate.id, db_session, admin)
    corrected = await update_catalog_import_candidate(
        first.id,
        candidate.id,
        CatalogCandidateUpdateRequest(metadata={"publisher": "外研社"}),
        db_session,
        admin,
    )
    assert corrected.status is CatalogCandidateStatus.STAGED

    approved = await approve_catalog_import_candidate(first.id, candidate.id, db_session, admin)
    replayed = await approve_catalog_import_candidate(first.id, candidate.id, db_session, admin)
    assert replayed == approved
    assert await db_session.scalar(select(func.count(Book.id))) == 1
    assert await db_session.scalar(select(func.count(Course.id))) == 1
    ingestion = await db_session.get(OutboxEvent, approved.ingestion_job_id)
    assert ingestion is not None
    assert ingestion.payload["include_relative_paths"] == [candidate.relative_path]

    course = await db_session.get(Course, approved.course_id)
    course_run = await db_session.get(CourseRun, approved.course_run_id)
    assert course is not None and course_run is not None
    assert course_run.access_policy is CourseAccessPolicy.TENANT_AUTHENTICATED
    learner = Principal(
        user_id=uuid.uuid4(),
        tenant_id=tenant_id,
        role=UserRole.STUDENT,
        access_label=AccessLabel.ENROLLED,
        subject="catalog-learner",
        course_ids=frozenset(),
    )
    assert await principal_can_access_course_record(db_session, learner, course)

    before_publish = await search_catalog_books(db_session, learner)
    assert before_publish.items == ()
    version = ContentVersion(
        id=uuid.uuid4(),
        course_id=course.id,
        course_run_id=course_run.id,
        pipeline_version="catalog-test",
        sequence=1,
        status=ContentVersionStatus.READY,
        embedding_model_version="test-embedding",
        embedding_dimension=8,
        source_snapshot_hash="a" * 64,
    )
    db_session.add(version)
    await db_session.flush()
    source = SourceDocument(
        id=uuid.uuid4(),
        version_id=version.id,
        relative_path=candidate.relative_path,
        checksum=candidate.checksum,
        mime_type="application/pdf",
        size_bytes=candidate.size_bytes,
        access_label=AccessLabel.ENROLLED,
        extraction_status=ExtractionStatus.EXTRACTED,
        extraction_confidence=1.0,
        source_metadata={},
    )
    db_session.add(source)
    await db_session.flush()
    db_session.add(ContentVersionSource(version_id=version.id, source_id=source.id))
    await db_session.commit()
    await publish_version(course.id, version.id, db_session, admin)

    page = await search_catalog_books(
        db_session,
        learner,
        education_level=EducationLevel.PRIMARY,
        publisher="外研社",
    )
    assert len(page.items) == 1
    detail = await get_catalog_book(page.items[0].id, db_session, learner)
    assert detail.courses[0].content_version_id == version.id
    assert await db_session.scalar(select(func.count(BookContentBinding.id))) == 1

    other_tenant = Principal(
        user_id=uuid.uuid4(),
        tenant_id=uuid.uuid4(),
        role=UserRole.STUDENT,
        access_label=AccessLabel.ENROLLED,
        subject="other-tenant",
        course_ids=frozenset(),
    )
    assert (await search_catalog_books(db_session, other_tenant)).items == ()


async def test_normal_course_still_requires_explicit_membership(
    db_session: AsyncSession, tmp_path: Path
) -> None:
    tenant_id = uuid.uuid4()
    db_session.add(Tenant(id=tenant_id, slug=f"normal-{tenant_id}", name="Normal"))
    await db_session.flush()
    root = SourceRoot(
        id=uuid.uuid4(),
        tenant_id=tenant_id,
        absolute_path=str(tmp_path),
        scan_interval_seconds=900,
        automatic_ingestion_enabled=False,
    )
    db_session.add(root)
    from course_tutor_api.db import Programme

    programme = Programme(id=uuid.uuid4(), tenant_id=tenant_id, code="NORMAL", name="Normal")
    db_session.add(programme)
    await db_session.flush()
    course = Course(
        id=uuid.uuid4(),
        tenant_id=tenant_id,
        programme_id=programme.id,
        code="NORMAL-1",
        name="Normal course",
        level=EducationLevel.PRIMARY,
        source_root_id=root.id,
        teaching_policy={},
    )
    db_session.add(course)
    await db_session.flush()
    db_session.add(
        CourseRun(
            id=uuid.uuid4(),
            course_id=course.id,
            run_key="2026",
            source_root_id=root.id,
            access_policy=CourseAccessPolicy.EXPLICIT_MEMBERSHIP,
        )
    )
    await db_session.commit()
    learner = Principal(
        user_id=uuid.uuid4(),
        tenant_id=tenant_id,
        role=UserRole.STUDENT,
        access_label=AccessLabel.ENROLLED,
        subject="learner",
        course_ids=frozenset(),
    )
    assert not await principal_can_access_course_record(db_session, learner, course)
