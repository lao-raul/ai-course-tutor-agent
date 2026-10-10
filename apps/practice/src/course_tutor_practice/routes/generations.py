"""Default StudyPlan, generation job and learner-safe PracticeSet routes."""

from __future__ import annotations

import uuid
from collections.abc import AsyncIterator
from typing import Annotated, cast
from uuid import UUID

from fastapi import APIRouter, Depends, Header, HTTPException, Request, status

from course_tutor_auth import Principal, get_current_principal, principal_can_access_course
from course_tutor_contracts import (
    CatalogBookDetail,
    CatalogCourseView,
    GeneratePracticeRequest,
    PracticeGenerationView,
    PracticeSetView,
    StudyPlanView,
)
from course_tutor_practice.adapters.agent_client import AgentCatalogClient, AgentCatalogError
from course_tutor_practice.application.generation import (
    GenerationService,
    StudyPlanService,
    generation_view,
    plan_view,
)
from course_tutor_practice.db.repository import SqlPracticeRepository
from course_tutor_practice.ports import OutlineProvider, PracticeRepository
from course_tutor_practice.ports.outline import UnavailableOutlineProvider
from course_tutor_shared import get_correlation_id

router = APIRouter(tags=["practice-generation"])


def _dependencies(request: Request):  # type: ignore[no-untyped-def]
    return request.app.state.dependencies


def _catalog(request: Request) -> AgentCatalogClient:
    client = _dependencies(request).catalog
    if client is None:
        raise HTTPException(status_code=503, detail="Agent catalog is unavailable")
    return cast("AgentCatalogClient", client)


def _outline(request: Request) -> OutlineProvider:
    return cast(
        "OutlineProvider",
        _dependencies(request).outline or UnavailableOutlineProvider(),
    )


async def _repository(request: Request) -> AsyncIterator[PracticeRepository]:
    dependencies = _dependencies(request)
    if dependencies.repository is not None:
        yield cast("PracticeRepository", dependencies.repository)
        return
    factory = dependencies.session_factory
    if factory is None:
        raise HTTPException(status_code=503, detail="Practice persistence is unavailable")
    async with factory() as session:
        yield SqlPracticeRepository(session)


def _course(courses: list[CatalogCourseView], requested: UUID | None) -> CatalogCourseView:
    if not courses:
        raise HTTPException(status_code=409, detail="book has no published course binding")
    if requested is None:
        return courses[0]
    match = next((item for item in courses if item.course_id == requested), None)
    if match is None:
        raise HTTPException(status_code=422, detail="course_id is not bound to this book")
    return match


async def _book_and_course(
    catalog: AgentCatalogClient,
    book_id: UUID,
    requested_course_id: UUID | None,
    bearer: str,
) -> tuple[CatalogBookDetail, CatalogCourseView]:
    try:
        book = await catalog.get_book(book_id, bearer, get_correlation_id())
        courses = await catalog.list_book_courses(book_id, bearer, get_correlation_id())
    except AgentCatalogError as exc:
        safe_status = exc.status_code if exc.status_code in {400, 401, 403, 404, 409, 422} else 503
        raise HTTPException(status_code=safe_status, detail=exc.detail) from exc
    return book, _course(courses, requested_course_id)


@router.get(
    "/v1/practice/catalog/books/{book_id}/study-plan",
    response_model=StudyPlanView,
    operation_id="getBookStudyPlan",
)
async def get_book_study_plan(
    book_id: UUID,
    principal: Annotated[Principal, Depends(get_current_principal)],
    bearer: Annotated[str, Header(alias="Authorization")],
    repository: Annotated[PracticeRepository, Depends(_repository)],
    catalog: Annotated[AgentCatalogClient, Depends(_catalog)],
    outline: Annotated[OutlineProvider, Depends(_outline)],
) -> StudyPlanView:
    book, course = await _book_and_course(catalog, book_id, None, bearer)
    plan = await StudyPlanService(repository, outline).ensure_default(
        principal, book, course, bearer, get_correlation_id()
    )
    return plan_view(plan)


@router.post(
    "/v1/practice/catalog/books/{book_id}/generations",
    response_model=PracticeGenerationView,
    status_code=status.HTTP_202_ACCEPTED,
    operation_id="createPracticeGeneration",
)
async def create_practice_generation(
    book_id: UUID,
    body: GeneratePracticeRequest,
    principal: Annotated[Principal, Depends(get_current_principal)],
    bearer: Annotated[str, Header(alias="Authorization")],
    idempotency_key: Annotated[str, Header(alias="Idempotency-Key", min_length=1, max_length=255)],
    repository: Annotated[PracticeRepository, Depends(_repository)],
    catalog: Annotated[AgentCatalogClient, Depends(_catalog)],
    outline: Annotated[OutlineProvider, Depends(_outline)],
) -> PracticeGenerationView:
    book, course = await _book_and_course(catalog, book_id, body.course_id, bearer)
    plan = await StudyPlanService(repository, outline).ensure_default(
        principal, book, course, bearer, get_correlation_id()
    )
    try:
        job, _created = await GenerationService(repository).submit(
            principal,
            plan,
            body,
            idempotency_key,
            get_correlation_id() or str(uuid.uuid4()),
        )
    except ValueError as exc:
        raise HTTPException(status_code=422, detail=str(exc)) from exc
    return generation_view(job)


@router.get(
    "/v1/practice/generations/{generation_id}",
    response_model=PracticeGenerationView,
    operation_id="getPracticeGeneration",
)
async def get_practice_generation(
    generation_id: UUID,
    principal: Annotated[Principal, Depends(get_current_principal)],
    repository: Annotated[PracticeRepository, Depends(_repository)],
) -> PracticeGenerationView:
    job = await repository.get_generation(principal.tenant_id, principal.user_id, generation_id)
    if job is None:
        raise HTTPException(status_code=404, detail="generation not found")
    return generation_view(job)


@router.post(
    "/v1/practice/generations/{generation_id}/cancel",
    response_model=PracticeGenerationView,
    operation_id="cancelPracticeGeneration",
)
async def cancel_practice_generation(
    generation_id: UUID,
    principal: Annotated[Principal, Depends(get_current_principal)],
    repository: Annotated[PracticeRepository, Depends(_repository)],
) -> PracticeGenerationView:
    job = await repository.cancel_generation(principal.tenant_id, principal.user_id, generation_id)
    if job is None:
        raise HTTPException(status_code=404, detail="generation not found")
    return generation_view(job)


@router.get(
    "/v1/practice/sets/{set_id}",
    response_model=PracticeSetView,
    operation_id="getPracticeSet",
)
async def get_practice_set(
    set_id: UUID,
    principal: Annotated[Principal, Depends(get_current_principal)],
    repository: Annotated[PracticeRepository, Depends(_repository)],
) -> PracticeSetView:
    value = await repository.get_practice_set(principal.tenant_id, principal.user_id, set_id)
    if value is None:
        raise HTTPException(status_code=404, detail="practice set not found")
    return PracticeSetView(
        id=value.id,
        generation_id=value.generation_id,
        study_plan_id=value.study_plan_id,
        book_id=value.book_id,
        course_id=value.course_id,
        content_version_id=value.content_version_id,
        exercises=value.exercises,
        created_at=value.created_at,
    )


@router.post(
    "/v1/practice/courses/{course_id}/exercises:generate",
    response_model=PracticeGenerationView,
    status_code=status.HTTP_202_ACCEPTED,
    operation_id="generatePracticeExercises",
    deprecated=True,
)
async def generate_practice_exercises_compatibility(
    course_id: UUID,
    body: GeneratePracticeRequest,
    principal: Annotated[Principal, Depends(get_current_principal)],
    idempotency_key: Annotated[str, Header(alias="Idempotency-Key", min_length=1, max_length=255)],
    repository: Annotated[PracticeRepository, Depends(_repository)],
) -> PracticeGenerationView:
    if not principal_can_access_course(principal, course_id):
        raise HTTPException(status_code=403, detail="course is outside the authenticated scope")
    plan = await repository.find_study_plan_by_course(principal.tenant_id, course_id)
    if plan is None:
        raise HTTPException(
            status_code=409,
            detail="initialize the book StudyPlan through the canonical book endpoint first",
        )
    compatible = body.model_copy(update={"course_id": course_id, "study_plan_id": plan.id})
    try:
        job, _created = await GenerationService(repository).submit(
            principal,
            plan,
            compatible,
            idempotency_key,
            get_correlation_id() or str(uuid.uuid4()),
        )
    except ValueError as exc:
        raise HTTPException(status_code=422, detail=str(exc)) from exc
    return generation_view(job)
