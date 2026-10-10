"""Shared study dependencies and live Agent publication checks."""

from __future__ import annotations

from collections.abc import AsyncIterator
from typing import cast
from uuid import UUID

from fastapi import HTTPException, Request

from course_tutor_contracts import BookLifecycleStatus
from course_tutor_practice.adapters.agent_client import AgentCatalogClient, AgentCatalogError
from course_tutor_practice.application.evaluation import RubricEvaluator
from course_tutor_practice.db.study_repository import SqlStudyRepository
from course_tutor_practice.ports.study import StudyRepository
from course_tutor_shared import get_correlation_id


def catalog(request: Request) -> AgentCatalogClient:
    result = request.app.state.dependencies.catalog
    if result is None:
        raise HTTPException(status_code=503, detail="Agent catalog is unavailable")
    return cast("AgentCatalogClient", result)


async def study_repository(request: Request) -> AsyncIterator[StudyRepository]:
    dependencies = request.app.state.dependencies
    if dependencies.repository is not None:
        yield cast("StudyRepository", dependencies.repository)
        return
    if dependencies.session_factory is None:
        raise HTTPException(status_code=503, detail="Practice persistence is unavailable")
    async with dependencies.session_factory() as session:
        yield SqlStudyRepository(session)


def rubric_evaluator(request: Request) -> RubricEvaluator | None:
    return cast("RubricEvaluator | None", request.app.state.dependencies.rubric_evaluator)


async def ensure_published_access(
    client: AgentCatalogClient,
    bearer: str,
    book_id: UUID,
    course_id: UUID,
    content_version_id: UUID,
) -> bool:
    return await _authorized_binding(client, bearer, book_id, course_id, content_version_id)


async def ensure_book_access(
    client: AgentCatalogClient,
    bearer: str,
    book_id: UUID,
    course_id: UUID,
) -> bool:
    """Historical progress is visible while the learner retains current book access."""
    return await _authorized_binding(client, bearer, book_id, course_id, None)


async def _authorized_binding(
    client: AgentCatalogClient,
    bearer: str,
    book_id: UUID,
    course_id: UUID,
    content_version_id: UUID | None,
) -> bool:
    try:
        book = await client.get_book(book_id, bearer, get_correlation_id())
        courses = await client.list_book_courses(book_id, bearer, get_correlation_id())
    except AgentCatalogError as exc:
        if exc.status_code in {401, 403, 404, 409}:
            return False
        raise HTTPException(status_code=503, detail="Agent catalog is unavailable") from exc
    return (
        book.id == book_id
        and book.lifecycle_status is BookLifecycleStatus.PUBLISHED
        and any(
            item.course_id == course_id
            and (content_version_id is None or item.content_version_id == content_version_id)
            for item in courses
        )
    )
