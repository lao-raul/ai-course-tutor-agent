"""Product-facing catalog facade over Agent's versioned HTTP API."""

from __future__ import annotations

from typing import Annotated, Any, NoReturn, cast
from uuid import UUID

from fastapi import APIRouter, Depends, Header, HTTPException, Query, Request

from course_tutor_auth import Principal, get_current_principal
from course_tutor_contracts import (
    CatalogBookDetail,
    CatalogBookPage,
    CatalogCategoryView,
    CatalogCourseView,
    EducationLevel,
)
from course_tutor_practice.adapters.agent_client import AgentCatalogClient, AgentCatalogError
from course_tutor_shared import get_correlation_id

router = APIRouter(prefix="/v1/practice/catalog", tags=["catalog"])


def _client(request: Request) -> AgentCatalogClient:
    return cast("AgentCatalogClient", request.app.state.dependencies.catalog)


def _raise_agent_error(exc: AgentCatalogError) -> NoReturn:
    safe_status = exc.status_code if exc.status_code in {400, 401, 403, 404, 409, 422} else 503
    raise HTTPException(status_code=safe_status, detail=exc.detail) from exc


@router.get(
    "/categories",
    response_model=list[CatalogCategoryView],
    operation_id="listPracticeCategories",
)
async def list_practice_categories(
    client: Annotated[AgentCatalogClient, Depends(_client)],
    _principal: Annotated[Principal, Depends(get_current_principal)],
    authorization: Annotated[str, Header(alias="Authorization")],
) -> list[CatalogCategoryView]:
    try:
        return await client.list_categories(authorization, get_correlation_id())
    except AgentCatalogError as exc:
        _raise_agent_error(exc)


@router.get(
    "/books",
    response_model=CatalogBookPage,
    operation_id="searchPracticeBooks",
)
async def search_practice_books(
    client: Annotated[AgentCatalogClient, Depends(_client)],
    _principal: Annotated[Principal, Depends(get_current_principal)],
    authorization: Annotated[str, Header(alias="Authorization")],
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
    values: dict[str, Any] = {
        "q": q,
        "education_level": education_level.value if education_level else None,
        "grade": grade,
        "subject": subject,
        "publisher": publisher,
        "edition": edition,
        "term": term,
        "language": language,
        "cursor": cursor,
        "limit": limit,
    }
    params = {key: value for key, value in values.items() if value is not None}
    try:
        return await client.search_books(authorization, get_correlation_id(), params)
    except AgentCatalogError as exc:
        _raise_agent_error(exc)


@router.get(
    "/books/{book_id}",
    response_model=CatalogBookDetail,
    operation_id="getPracticeBook",
)
async def get_practice_book(
    book_id: UUID,
    client: Annotated[AgentCatalogClient, Depends(_client)],
    _principal: Annotated[Principal, Depends(get_current_principal)],
    authorization: Annotated[str, Header(alias="Authorization")],
) -> CatalogBookDetail:
    try:
        return await client.get_book(book_id, authorization, get_correlation_id())
    except AgentCatalogError as exc:
        _raise_agent_error(exc)


@router.get(
    "/books/{book_id}/courses",
    response_model=list[CatalogCourseView],
    operation_id="listBookCourses",
)
async def list_book_courses(
    book_id: UUID,
    client: Annotated[AgentCatalogClient, Depends(_client)],
    _principal: Annotated[Principal, Depends(get_current_principal)],
    authorization: Annotated[str, Header(alias="Authorization")],
) -> list[CatalogCourseView]:
    try:
        return await client.list_book_courses(book_id, authorization, get_correlation_id())
    except AgentCatalogError as exc:
        _raise_agent_error(exc)
