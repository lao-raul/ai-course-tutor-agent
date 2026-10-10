"""Real PostgreSQL proves the delegated evidence scope is checked by Agent."""

from __future__ import annotations

from datetime import UTC, datetime, timedelta
from types import SimpleNamespace
from uuid import uuid4

import pytest
from fastapi import HTTPException
from sqlalchemy.ext.asyncio import AsyncSession

from course_tutor_api.db import (
    Book,
    BookContentBinding,
    ContentVersion,
    Course,
    CourseRun,
    Programme,
    Publisher,
    SourceDocument,
    SourceRoot,
    Tenant,
)
from course_tutor_api.routes import practice_evidence
from course_tutor_api.routes.chat import EvidencePack
from course_tutor_auth import Principal
from course_tutor_auth.practice_delegation import issue_practice_delegation
from course_tutor_contracts import PracticeEvidenceRequest
from course_tutor_contracts.enums import (
    AccessLabel,
    BookLifecycleStatus,
    ContentVersionStatus,
    CourseAccessPolicy,
    EducationLevel,
    ExtractionStatus,
    UserRole,
)
from course_tutor_shared import Settings


async def _published_book(session: AsyncSession) -> tuple[object, object, object, object]:
    tenant = Tenant(id=uuid4(), slug=f"evidence-{uuid4()}", name="Evidence")
    session.add(tenant)
    await session.flush()
    root = SourceRoot(id=uuid4(), tenant_id=tenant.id, absolute_path="/redacted")
    programme = Programme(id=uuid4(), tenant_id=tenant.id, code="E", name="Evidence")
    publisher = Publisher(
        id=uuid4(),
        tenant_id=tenant.id,
        stable_key="publisher",
        display_name="Publisher",
        normalized_name="publisher",
        aliases=[],
    )
    session.add_all([root, programme, publisher])
    await session.flush()
    course = Course(
        id=uuid4(),
        tenant_id=tenant.id,
        programme_id=programme.id,
        code="E-1",
        name="Grade 3 English",
        level=EducationLevel.PRIMARY,
        source_root_id=root.id,
        teaching_policy={},
    )
    session.add(course)
    await session.flush()
    run = CourseRun(
        id=uuid4(),
        course_id=course.id,
        run_key="system",
        source_root_id=root.id,
        access_policy=CourseAccessPolicy.TENANT_AUTHENTICATED,
    )
    book = Book(
        id=uuid4(),
        tenant_id=tenant.id,
        stable_key="book",
        title="Grade 3 English",
        normalized_title="grade 3 english",
        education_level=EducationLevel.PRIMARY,
        subject="English",
        grade="3",
        publisher_id=publisher.id,
        series="FLTRP",
        term="first",
        language="en",
        lifecycle_status=BookLifecycleStatus.PUBLISHED,
    )
    session.add_all([run, book])
    await session.flush()
    version = ContentVersion(
        id=uuid4(),
        course_id=course.id,
        course_run_id=run.id,
        pipeline_version="test",
        sequence=1,
        status=ContentVersionStatus.PUBLISHED,
        embedding_model_version="fake",
        embedding_dimension=8,
    )
    session.add(version)
    await session.flush()
    course.active_content_version_id = version.id
    run.active_content_version_id = version.id
    source = SourceDocument(
        id=uuid4(),
        version_id=version.id,
        relative_path="redacted.pdf",
        checksum="a" * 64,
        mime_type="application/pdf",
        size_bytes=1,
        access_label=AccessLabel.ENROLLED,
        extraction_status=ExtractionStatus.EXTRACTED,
        extraction_confidence=1.0,
        source_metadata={},
    )
    session.add(source)
    await session.flush()
    session.add(
        BookContentBinding(
            id=uuid4(),
            book_id=book.id,
            course_run_id=run.id,
            source_root_id=root.id,
            source_id=source.id,
            content_version_id=version.id,
        )
    )
    await session.commit()
    return tenant, book, course, version


@pytest.mark.asyncio
async def test_delegation_requires_current_published_same_tenant_binding(
    db_session: AsyncSession, monkeypatch: pytest.MonkeyPatch
) -> None:
    tenant, book, course, version = await _published_book(db_session)
    request = PracticeEvidenceRequest(
        generation_id=uuid4(),
        book_id=book.id,
        course_id=course.id,
        content_version_id=version.id,
        query="Unit 1",
    )
    settings = Settings()
    deps = SimpleNamespace(settings=settings)
    calls = 0

    async def retrieve(**_kwargs):  # type: ignore[no-untyped-def]
        nonlocal calls
        calls += 1
        return EvidencePack(candidates=(), evidence=(), citation_map={}, timings_ms={})

    async def trace(*_args, **_kwargs):  # type: ignore[no-untyped-def]
        return uuid4()

    monkeypatch.setattr(practice_evidence, "_build_evidence_pack", retrieve)
    monkeypatch.setattr(practice_evidence, "_create_trace", trace)
    monkeypatch.setattr(practice_evidence, "_get_retrieval_service", lambda _deps: object())
    monkeypatch.setattr(practice_evidence, "_get_reranker", lambda: object())

    def authorization(tenant_id):  # type: ignore[no-untyped-def]
        principal = Principal(
            user_id=uuid4(),
            tenant_id=tenant_id,
            role=UserRole.STUDENT,
            access_label=AccessLabel.ENROLLED,
            subject="student",
        )
        token = issue_practice_delegation(
            principal,
            generation_id=request.generation_id,
            book_id=request.book_id,
            course_id=request.course_id,
            content_version_id=request.content_version_id,
            expires_at=datetime.now(UTC) + timedelta(minutes=5),
            secret=settings.practice_delegation_secret.get_secret_value(),
        )
        return f"Bearer {token}"

    result = await practice_evidence.retrieve_practice_evidence(
        request,
        db_session,
        deps,
        authorization(tenant.id),  # type: ignore[arg-type]
    )
    assert result.content_version_id == version.id and calls == 1

    with pytest.raises(HTTPException) as cross_tenant:
        await practice_evidence.retrieve_practice_evidence(
            request,
            db_session,
            deps,
            authorization(uuid4()),  # type: ignore[arg-type]
        )
    assert cross_tenant.value.status_code == 404 and calls == 1

    version.status = ContentVersionStatus.READY
    await db_session.commit()
    with pytest.raises(HTTPException) as unpublished:
        await practice_evidence.retrieve_practice_evidence(
            request,
            db_session,
            deps,
            authorization(tenant.id),  # type: ignore[arg-type]
        )
    assert unpublished.value.status_code == 404 and calls == 1

    version.status = ContentVersionStatus.PUBLISHED
    course.active_content_version_id = None
    await db_session.commit()
    with pytest.raises(HTTPException) as stale:
        await practice_evidence.retrieve_practice_evidence(
            request,
            db_session,
            deps,
            authorization(tenant.id),  # type: ignore[arg-type]
        )
    assert stale.value.status_code == 404 and calls == 1
