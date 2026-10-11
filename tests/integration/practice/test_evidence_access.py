"""Real PostgreSQL proves the delegated evidence scope is checked by Agent."""

from __future__ import annotations

from datetime import UTC, datetime, timedelta
from types import SimpleNamespace
from uuid import uuid4

import pytest
from fastapi import HTTPException
from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession

from course_tutor_api.db import (
    Book,
    BookContentBinding,
    BookOutline,
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
        source_metadata={"page_count": 83},
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


@pytest.mark.asyncio
async def test_outline_node_restricts_evidence_to_its_bound_source_and_pages(
    db_session: AsyncSession, monkeypatch: pytest.MonkeyPatch
) -> None:
    tenant, book, course, version = await _published_book(db_session)
    source = await db_session.scalar(
        select(SourceDocument).where(SourceDocument.version_id == version.id)
    )
    assert source is not None
    db_session.add(
        BookOutline(
            id=uuid4(),
            book_id=book.id,
            content_version_id=version.id,
            source_id=source.id,
            extractor_version="fixture",
            availability="available",
            provenance="text_toc",
            confidence=0.92,
            nodes=[
                {
                    "id": "sam",
                    "ordinal": 0,
                    "title": "Unit 1 I'm Sam",
                    "page_start": 7,
                    "page_end": None,
                    "depth": 1,
                },
                {
                    "id": "how",
                    "ordinal": 1,
                    "title": "Unit 2 How are you",
                    "page_start": 10,
                    "page_end": None,
                    "depth": 1,
                },
            ],
        )
    )
    await db_session.commit()
    principal = Principal(
        user_id=uuid4(),
        tenant_id=tenant.id,
        role=UserRole.STUDENT,
        access_label=AccessLabel.ENROLLED,
        subject="student",
    )
    request = PracticeEvidenceRequest(
        generation_id=uuid4(),
        book_id=book.id,
        course_id=course.id,
        content_version_id=version.id,
        query="Unit 1 I'm Sam",
        outline_node_id="sam",
    )
    token = issue_practice_delegation(
        principal,
        generation_id=request.generation_id,
        book_id=book.id,
        course_id=course.id,
        content_version_id=version.id,
        expires_at=datetime.now(UTC) + timedelta(minutes=5),
        secret=Settings().practice_delegation_secret.get_secret_value(),
    )
    observed: dict[str, object] = {}

    async def retrieve(**kwargs):  # type: ignore[no-untyped-def]
        observed.update(kwargs)
        return EvidencePack(candidates=(), evidence=(), citation_map={}, timings_ms={})

    async def trace(*_args, **_kwargs):  # type: ignore[no-untyped-def]
        return uuid4()

    monkeypatch.setattr(practice_evidence, "_build_evidence_pack", retrieve)
    monkeypatch.setattr(practice_evidence, "_create_trace", trace)
    monkeypatch.setattr(practice_evidence, "_get_retrieval_service", lambda _deps: object())
    monkeypatch.setattr(practice_evidence, "_get_reranker", lambda: object())
    result = await practice_evidence.retrieve_practice_evidence(
        request, db_session, SimpleNamespace(settings=Settings()), f"Bearer {token}"
    )
    assert result.chunks == ()
    assert observed["page_range"] == (7, 9)
    assert observed["source_ids"] == (source.id,)

    with pytest.raises(HTTPException) as unknown:
        await practice_evidence.retrieve_practice_evidence(
            request.model_copy(update={"outline_node_id": "another-unit"}),
            db_session,
            SimpleNamespace(settings=Settings()),
            f"Bearer {token}",
        )
    assert unknown.value.status_code == 422
