from __future__ import annotations

import uuid

import pytest
from fastapi import HTTPException
from sqlalchemy.ext.asyncio import AsyncSession

from course_tutor_api.auth import Principal
from course_tutor_api.db import (
    Book,
    BookContentBinding,
    BookCourseBinding,
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
from course_tutor_api.routes.catalog_outline import get_catalog_book_outline
from course_tutor_contracts.enums import (
    AccessLabel,
    BookLifecycleStatus,
    ContentVersionStatus,
    CourseAccessPolicy,
    EducationLevel,
    ExtractionStatus,
    UserRole,
)


async def test_outline_only_serves_the_current_published_tenant_version(
    db_session: AsyncSession,
) -> None:
    tenant_id = uuid.uuid4()
    db_session.add(Tenant(id=tenant_id, slug=f"outline-{tenant_id}", name="Outline"))
    await db_session.flush()
    root = SourceRoot(id=uuid.uuid4(), tenant_id=tenant_id, absolute_path="/redacted")
    programme = Programme(id=uuid.uuid4(), tenant_id=tenant_id, code="O", name="Outline")
    publisher = Publisher(
        id=uuid.uuid4(),
        tenant_id=tenant_id,
        stable_key="publisher",
        display_name="Publisher",
        normalized_name="publisher",
        aliases=[],
    )
    db_session.add_all([root, programme, publisher])
    await db_session.flush()
    course = Course(
        id=uuid.uuid4(),
        tenant_id=tenant_id,
        programme_id=programme.id,
        code="O-1",
        name="Outline",
        level=EducationLevel.PRIMARY,
        source_root_id=root.id,
        teaching_policy={},
    )
    db_session.add(course)
    await db_session.flush()
    run = CourseRun(
        id=uuid.uuid4(),
        course_id=course.id,
        run_key="2026",
        source_root_id=root.id,
        access_policy=CourseAccessPolicy.TENANT_AUTHENTICATED,
    )
    book = Book(
        id=uuid.uuid4(),
        tenant_id=tenant_id,
        stable_key="book",
        title="Book",
        normalized_title="book",
        education_level=EducationLevel.PRIMARY,
        subject="English",
        grade="3",
        publisher_id=publisher.id,
        series="Series",
        term="first",
        language="en",
        lifecycle_status=BookLifecycleStatus.PUBLISHED,
    )
    db_session.add_all([run, book])
    await db_session.flush()
    db_session.add(BookCourseBinding(book_id=book.id, course_run_id=run.id))
    await db_session.flush()
    version = ContentVersion(
        id=uuid.uuid4(),
        course_id=course.id,
        course_run_id=run.id,
        pipeline_version="outline",
        sequence=1,
        status=ContentVersionStatus.PUBLISHED,
        embedding_model_version="test",
        embedding_dimension=8,
        source_snapshot_hash="a" * 64,
    )
    db_session.add(version)
    await db_session.flush()
    course.active_content_version_id = version.id
    run.active_content_version_id = version.id
    source = SourceDocument(
        id=uuid.uuid4(),
        version_id=version.id,
        relative_path="redacted.pdf",
        checksum="b" * 64,
        mime_type="application/pdf",
        size_bytes=1,
        access_label=AccessLabel.ENROLLED,
        extraction_status=ExtractionStatus.EXTRACTED,
        extraction_confidence=1.0,
        source_metadata={},
    )
    db_session.add(source)
    await db_session.flush()
    outline_model = BookOutline(
        id=uuid.uuid4(),
        book_id=book.id,
        content_version_id=version.id,
        source_id=source.id,
        extractor_version="pdf-outline-v2",
        availability="available",
        provenance="pdf_bookmarks",
        confidence=0.98,
        reason=None,
        nodes=[
            {
                "id": "ol_1",
                "parent_id": None,
                "ordinal": 0,
                "title": "Unit 1",
                "page_start": 1,
                "page_end": None,
                "depth": 0,
            }
        ],
    )
    db_session.add_all(
        [
            BookContentBinding(
                id=uuid.uuid4(),
                book_id=book.id,
                course_run_id=run.id,
                source_root_id=root.id,
                source_id=source.id,
                content_version_id=version.id,
            ),
            outline_model,
        ]
    )
    await db_session.commit()
    principal = Principal(
        user_id=uuid.uuid4(),
        tenant_id=tenant_id,
        role=UserRole.STUDENT,
        access_label=AccessLabel.ENROLLED,
        subject="learner",
        course_ids=frozenset(),
    )

    outline = await get_catalog_book_outline(book.id, db_session, principal, version.id)
    assert outline.content_version_id == version.id
    assert outline.nodes[0].title == "Unit 1"
    assert "relative_path" not in outline.model_dump()

    with pytest.raises(HTTPException, match="not found"):
        await get_catalog_book_outline(book.id, db_session, principal, uuid.uuid4())
    with pytest.raises(HTTPException, match="not found"):
        await get_catalog_book_outline(
            book.id,
            db_session,
            Principal(
                user_id=uuid.uuid4(),
                tenant_id=uuid.uuid4(),
                role=UserRole.STUDENT,
                access_label=AccessLabel.ENROLLED,
                subject="other",
                course_ids=frozenset(),
            ),
            version.id,
        )

    version.status = ContentVersionStatus.READY
    await db_session.commit()
    with pytest.raises(HTTPException, match="not found"):
        await get_catalog_book_outline(book.id, db_session, principal, version.id)

    version.status = ContentVersionStatus.PUBLISHED
    course.active_content_version_id = None
    await db_session.commit()
    with pytest.raises(HTTPException, match="not found"):
        await get_catalog_book_outline(book.id, db_session, principal, version.id)

    course.active_content_version_id = version.id
    outline_model.availability = "unavailable"
    outline_model.provenance = "none"
    outline_model.confidence = 0
    outline_model.reason = "no_reliable_structure"
    # Defensive API behavior must not expose stale nodes for an unavailable outline.
    await db_session.commit()
    unavailable = await get_catalog_book_outline(book.id, db_session, principal, version.id)
    assert unavailable.nodes == ()
    assert unavailable.reason == "no_reliable_structure"
