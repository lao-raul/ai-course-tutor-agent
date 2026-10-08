"""Tenant-authorized published textbook catalog reads."""

from __future__ import annotations

import base64
import json
import unicodedata
from typing import Annotated
from uuid import UUID

from fastapi import APIRouter, Depends, HTTPException, Query, status
from sqlalchemy import and_, exists, func, or_, select
from sqlalchemy.ext.asyncio import AsyncSession
from sqlalchemy.sql.elements import ColumnElement

from course_tutor_api.auth import Principal, get_current_principal
from course_tutor_api.db import (
    Book,
    BookCourseBinding,
    Category,
    ContentVersion,
    Course,
    CourseRun,
    Publisher,
)
from course_tutor_api.dependencies import get_session
from course_tutor_contracts import (
    BookLifecycleStatus,
    CatalogBookDetail,
    CatalogBookPage,
    CatalogBookSummary,
    CatalogCategoryView,
    CatalogCourseView,
    ContentVersionStatus,
    CourseAccessPolicy,
    EducationLevel,
)

router = APIRouter(prefix="/v1/catalog", tags=["catalog"])


def _normalize(value: str) -> str:
    return " ".join(unicodedata.normalize("NFKC", value).strip().split()).casefold()


def _published_binding_exists() -> ColumnElement[bool]:
    return exists(
        select(BookCourseBinding.book_id)
        .join(CourseRun, CourseRun.id == BookCourseBinding.course_run_id)
        .join(Course, Course.id == CourseRun.course_id)
        .join(ContentVersion, ContentVersion.id == CourseRun.active_content_version_id)
        .where(
            BookCourseBinding.book_id == Book.id,
            Course.active_content_version_id == CourseRun.active_content_version_id,
            CourseRun.access_policy == CourseAccessPolicy.TENANT_AUTHENTICATED,
            ContentVersion.status == ContentVersionStatus.PUBLISHED,
        )
    )


def _summary(book: Book, publisher: Publisher) -> CatalogBookSummary:
    return CatalogBookSummary(
        id=book.id,
        title=book.title,
        education_level=book.education_level,
        subject=book.subject,
        grade=book.grade,
        publisher=publisher.display_name,
        series=book.series,
        edition=book.edition,
        start_grade=book.start_grade,
        editor=book.editor,
        term=book.term,
        language=book.language,
        isbn=book.isbn,
        cover_uri=book.cover_uri,
        lifecycle_status=book.lifecycle_status,
    )


def _encode_cursor(book: Book) -> str:
    payload = json.dumps(
        [book.normalized_title, book.edition or "", str(book.id)],
        ensure_ascii=False,
        separators=(",", ":"),
    ).encode()
    return base64.urlsafe_b64encode(payload).decode().rstrip("=")


def _decode_cursor(value: str) -> tuple[str, str, UUID]:
    try:
        padded = value + "=" * (-len(value) % 4)
        title, edition, raw_id = json.loads(base64.urlsafe_b64decode(padded).decode())
        return str(title), str(edition), UUID(str(raw_id))
    except (ValueError, TypeError, json.JSONDecodeError) as exc:
        raise HTTPException(
            status_code=status.HTTP_422_UNPROCESSABLE_ENTITY,
            detail="invalid catalog cursor",
        ) from exc


async def _published_book_rows(
    session: AsyncSession, principal: Principal
) -> list[tuple[Book, Publisher]]:
    result = await session.execute(
        select(Book, Publisher)
        .join(Publisher, Publisher.id == Book.publisher_id)
        .where(
            Book.tenant_id == principal.tenant_id,
            Book.lifecycle_status == BookLifecycleStatus.PUBLISHED,
            _published_binding_exists(),
        )
    )
    return [(book, publisher) for book, publisher in result.tuples().all()]


@router.get(
    "/categories",
    response_model=list[CatalogCategoryView],
    operation_id="listCatalogCategories",
)
async def list_catalog_categories(
    session: Annotated[AsyncSession, Depends(get_session)],
    principal: Annotated[Principal, Depends(get_current_principal)],
) -> list[CatalogCategoryView]:
    categories = (
        (
            await session.execute(
                select(Category)
                .where(Category.tenant_id == principal.tenant_id)
                .order_by(Category.category_type, Category.stable_key, Category.id)
            )
        )
        .scalars()
        .all()
    )
    rows = await _published_book_rows(session, principal)
    counts: dict[str, int] = {}
    for book, publisher in rows:
        keys = (
            f"education:{book.education_level.value}",
            f"subject:{book.education_level.value}:{book.subject}",
            f"grade:{book.education_level.value}:{book.subject}:{book.grade}",
            f"publisher:{publisher.normalized_name}",
        )
        for key in keys:
            counts[key] = counts.get(key, 0) + 1
    return [
        CatalogCategoryView(
            id=category.id,
            stable_key=category.stable_key,
            display_name=category.display_name,
            category_type=category.category_type,
            parent_id=category.parent_id,
            book_count=counts.get(category.stable_key, 0),
        )
        for category in categories
        if counts.get(category.stable_key, 0) > 0
    ]


@router.get(
    "/books",
    response_model=CatalogBookPage,
    operation_id="searchCatalogBooks",
)
async def search_catalog_books(
    session: Annotated[AsyncSession, Depends(get_session)],
    principal: Annotated[Principal, Depends(get_current_principal)],
    q: Annotated[str | None, Query(max_length=255)] = None,
    education_level: EducationLevel | None = None,
    grade: Annotated[str | None, Query(max_length=64)] = None,
    subject: Annotated[str | None, Query(max_length=128)] = None,
    publisher: Annotated[str | None, Query(max_length=255)] = None,
    edition: Annotated[str | None, Query(max_length=255)] = None,
    term: Annotated[str | None, Query(max_length=64)] = None,
    language: Annotated[str | None, Query(max_length=16)] = None,
    cursor: str | None = None,
    limit: Annotated[int, Query(ge=1, le=100)] = 20,
) -> CatalogBookPage:
    query = (
        select(Book, Publisher)
        .join(Publisher, Publisher.id == Book.publisher_id)
        .where(
            Book.tenant_id == principal.tenant_id,
            Book.lifecycle_status == BookLifecycleStatus.PUBLISHED,
            _published_binding_exists(),
        )
    )
    if q:
        needle = f"%{_normalize(q)}%"
        query = query.where(
            or_(
                Book.normalized_title.ilike(needle),
                Book.subject.ilike(needle),
                Book.series.ilike(needle),
                Publisher.normalized_name.ilike(needle),
            )
        )
    filters = (
        (Book.education_level, education_level),
        (Book.grade, grade),
        (Book.subject, subject),
        (Book.edition, edition),
        (Book.term, term),
        (Book.language, language),
    )
    for column, value in filters:
        if value is not None:
            query = query.where(column == value)
    if publisher is not None:
        query = query.where(Publisher.normalized_name == _normalize(publisher))
    if cursor:
        cursor_title, cursor_edition, cursor_id = _decode_cursor(cursor)
        query = query.where(
            or_(
                Book.normalized_title > cursor_title,
                and_(
                    Book.normalized_title == cursor_title,
                    func.coalesce(Book.edition, "") > cursor_edition,
                ),
                and_(
                    Book.normalized_title == cursor_title,
                    func.coalesce(Book.edition, "") == cursor_edition,
                    Book.id > cursor_id,
                ),
            )
        )
    result = await session.execute(
        query.order_by(Book.normalized_title, Book.edition.nullsfirst(), Book.id).limit(limit + 1)
    )
    rows = list(result.all())
    page = rows[:limit]
    next_cursor = _encode_cursor(page[-1][0]) if len(rows) > limit and page else None
    return CatalogBookPage(
        items=tuple(_summary(book, publisher_row) for book, publisher_row in page),
        next_cursor=next_cursor,
    )


async def _book_courses(
    session: AsyncSession,
    principal: Principal,
    book_id: UUID,
) -> tuple[CatalogCourseView, ...]:
    result = await session.execute(
        select(Course, CourseRun, ContentVersion)
        .join(CourseRun, CourseRun.course_id == Course.id)
        .join(BookCourseBinding, BookCourseBinding.course_run_id == CourseRun.id)
        .join(ContentVersion, ContentVersion.id == CourseRun.active_content_version_id)
        .where(
            BookCourseBinding.book_id == book_id,
            Course.tenant_id == principal.tenant_id,
            Course.active_content_version_id == CourseRun.active_content_version_id,
            CourseRun.access_policy == CourseAccessPolicy.TENANT_AUTHENTICATED,
            ContentVersion.status == ContentVersionStatus.PUBLISHED,
        )
        .order_by(Course.code, CourseRun.run_key, CourseRun.id)
    )
    return tuple(
        CatalogCourseView(
            course_id=course.id,
            course_run_id=course_run.id,
            code=course.code,
            name=course.name,
            content_version_id=version.id,
        )
        for course, course_run, version in result.all()
    )


async def _get_published_book(
    session: AsyncSession, principal: Principal, book_id: UUID
) -> tuple[Book, Publisher]:
    result = await session.execute(
        select(Book, Publisher)
        .join(Publisher, Publisher.id == Book.publisher_id)
        .where(
            Book.id == book_id,
            Book.tenant_id == principal.tenant_id,
            Book.lifecycle_status == BookLifecycleStatus.PUBLISHED,
            _published_binding_exists(),
        )
    )
    row = result.tuples().one_or_none()
    if row is None:
        raise HTTPException(status_code=status.HTTP_404_NOT_FOUND, detail="book not found")
    book, publisher = row
    return book, publisher


@router.get(
    "/books/{book_id}",
    response_model=CatalogBookDetail,
    operation_id="getCatalogBook",
)
async def get_catalog_book(
    book_id: UUID,
    session: Annotated[AsyncSession, Depends(get_session)],
    principal: Annotated[Principal, Depends(get_current_principal)],
) -> CatalogBookDetail:
    book, publisher = await _get_published_book(session, principal, book_id)
    summary = _summary(book, publisher)
    courses = await _book_courses(session, principal, book.id)
    return CatalogBookDetail(**summary.model_dump(), courses=courses)


@router.get(
    "/books/{book_id}/courses",
    response_model=list[CatalogCourseView],
    operation_id="listCatalogBookCourses",
)
async def list_catalog_book_courses(
    book_id: UUID,
    session: Annotated[AsyncSession, Depends(get_session)],
    principal: Annotated[Principal, Depends(get_current_principal)],
) -> list[CatalogCourseView]:
    await _get_published_book(session, principal, book_id)
    return list(await _book_courses(session, principal, book_id))
