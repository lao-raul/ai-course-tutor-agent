"""Instructor-only answer preview; never shares the learner response path."""

from collections.abc import AsyncIterator
from typing import Annotated
from uuid import UUID, uuid4

from fastapi import APIRouter, Depends, Header, HTTPException, Request, Response
from pydantic import TypeAdapter, ValidationError
from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession

from course_tutor_auth import Principal, get_current_principal
from course_tutor_contracts import CatalogCitationResolveRequest
from course_tutor_contracts.enums import UserRole
from course_tutor_contracts.practice import (
    ExerciseDraft,
    InstructorExercisePreview,
    InstructorPracticePreview,
)
from course_tutor_practice.adapters.agent_client import AgentCatalogClient, AgentCatalogError
from course_tutor_practice.application.preview import can_preview_course
from course_tutor_practice.db.models import Exercise, GenerationJob, PracticeSet, PreviewAudit
from course_tutor_practice.routes.generations import _catalog
from course_tutor_practice.routes.study_dependencies import ensure_published_access
from course_tutor_shared import get_correlation_id

router = APIRouter(tags=["instructor-preview"])


async def preview_session(request: Request) -> AsyncIterator[AsyncSession]:
    factory = request.app.state.dependencies.session_factory
    if factory is None:
        raise HTTPException(503, "Preview persistence unavailable")
    async with factory() as session:
        yield session


async def instructor(
    principal: Annotated[Principal, Depends(get_current_principal)],
) -> Principal:
    if principal.role != UserRole.INSTRUCTOR or not principal.course_ids:
        raise HTTPException(403, "Instructor course assignment required")
    return principal


@router.get("/v1/practice/instructor/access", operation_id="getInstructorPreviewAccess")
async def preview_access(
    response: Response,
    principal: Annotated[Principal, Depends(instructor)],
) -> dict[str, bool]:
    response.headers["Cache-Control"] = "no-store"
    return {"enabled": bool(principal.course_ids)}


@router.get(
    "/v1/practice/sets/{set_id}/preview",
    response_model=InstructorPracticePreview,
    operation_id="previewPracticeSet",
)
async def preview_set(
    set_id: UUID,
    response: Response,
    principal: Annotated[Principal, Depends(instructor)],
    bearer: Annotated[str, Header(alias="Authorization")],
    session: Annotated[AsyncSession, Depends(preview_session)],
    catalog: Annotated[AgentCatalogClient, Depends(_catalog)],
) -> InstructorPracticePreview:
    response.headers["Cache-Control"] = "no-store"
    response.headers["Vary"] = "Authorization"
    model = await session.scalar(
        select(PracticeSet)
        .join(GenerationJob, GenerationJob.id == PracticeSet.generation_job_id)
        .where(
            PracticeSet.id == set_id,
            PracticeSet.tenant_id == principal.tenant_id,
            GenerationJob.tenant_id == principal.tenant_id,
            GenerationJob.status == "ready",
        )
    )
    if (
        model is None
        or not can_preview_course(
            principal, tenant_id=model.tenant_id, course_id=model.agent_course_id
        )
        or not await ensure_published_access(
            catalog,
            bearer,
            model.agent_book_id,
            model.agent_course_id,
            model.agent_content_version_id,
        )
    ):
        raise HTTPException(404, "Practice set not found")
    rows = (
        await session.scalars(
            select(Exercise).where(Exercise.practice_set_id == model.id).order_by(Exercise.ordinal)
        )
    ).all()
    adapter: TypeAdapter[ExerciseDraft] = TypeAdapter(ExerciseDraft)
    exercises = []
    for row in rows:
        data = {
            key: value for key, value in row.presentation.items() if key not in {"id", "ordinal"}
        }
        data.update(row.protected_answer)
        data["rationale"] = row.rationale
        try:
            question = adapter.validate_python(data)
        except ValidationError:
            # Validation errors include input values: never expose/log protected data.
            raise HTTPException(503, "Preview data unavailable") from None
        exercises.append(
            InstructorExercisePreview(
                id=row.id,
                ordinal=row.ordinal,
                revision=row.fingerprint,
                question=question,
            )
        )
    try:
        sources = await catalog.resolve_citations(
            model.agent_book_id,
            CatalogCitationResolveRequest(
                course_id=model.agent_course_id,
                content_version_id=model.agent_content_version_id,
                chunk_ids=tuple(
                    dict.fromkeys(UUID(c) for row in rows for c in row.evidence_citation_ids)
                ),
            ),
            bearer,
            get_correlation_id(),
        )
    except AgentCatalogError as exc:
        raise HTTPException(503, "Evidence unavailable") from exc
    result = InstructorPracticePreview(
        id=model.id,
        book_id=model.agent_book_id,
        course_id=model.agent_course_id,
        content_version_id=model.agent_content_version_id,
        model_version=model.model_version,
        prompt_version=model.prompt_version,
        validator_version=model.validator_version,
        exercises=tuple(exercises),
        evidence_sources=tuple(sources),
    )
    session.add(
        PreviewAudit(
            tenant_id=principal.tenant_id,
            actor_id=principal.user_id,
            set_id=model.id,
            content_version_id=model.agent_content_version_id,
            correlation_id=get_correlation_id() or str(uuid4()),
        )
    )
    await session.commit()  # No protected response is returned if auditing fails.
    return result
