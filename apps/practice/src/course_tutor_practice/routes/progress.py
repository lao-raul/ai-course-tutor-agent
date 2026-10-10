"""Read-only derived status, authorization-safe resume and explicit consent."""

from __future__ import annotations

from typing import Annotated

from fastapi import APIRouter, Depends, Header, HTTPException, Response, status

from course_tutor_auth import Principal, get_current_principal
from course_tutor_contracts import (
    ResumeView,
    StudyMemoryConsentRequest,
    StudyMemoryConsentView,
    StudyMemorySignalView,
    StudySetProgressView,
    StudyStatusView,
)
from course_tutor_practice.adapters.agent_client import AgentCatalogClient
from course_tutor_practice.application.progress import (
    memory_signal,
    resume_candidate,
    resume_view,
    summarize_plans,
)
from course_tutor_practice.ports.study import StudyRepository
from course_tutor_practice.routes.study_dependencies import (
    catalog,
    ensure_book_access,
    ensure_published_access,
    study_repository,
)

router = APIRouter(prefix="/v1/practice", tags=["practice-progress"])


async def _authorized_progress(
    repo: StudyRepository, principal: Principal, bearer: str, agent: AgentCatalogClient
) -> tuple[StudySetProgressView, ...]:
    all_progress = await repo.list_progress(principal.tenant_id, principal.user_id)
    allowed = []
    for item in all_progress:
        if await ensure_book_access(agent, bearer, item.book_id, item.course_id):
            allowed.append(item)
    return tuple(allowed)


@router.get("/study-status", response_model=StudyStatusView, operation_id="getStudyStatus")
async def get_study_status(
    principal: Annotated[Principal, Depends(get_current_principal)],
    bearer: Annotated[str, Header(alias="Authorization")],
    repo: Annotated[StudyRepository, Depends(study_repository)],
    agent: Annotated[AgentCatalogClient, Depends(catalog)],
) -> StudyStatusView:
    sets = await _authorized_progress(repo, principal, bearer, agent)
    return StudyStatusView(sets=sets, plans=summarize_plans(sets))


@router.get("/resume", response_model=ResumeView | None, operation_id="resumeStudy")
async def resume_study(
    principal: Annotated[Principal, Depends(get_current_principal)],
    bearer: Annotated[str, Header(alias="Authorization")],
    repo: Annotated[StudyRepository, Depends(study_repository)],
    agent: Annotated[AgentCatalogClient, Depends(catalog)],
) -> ResumeView | None:
    # Keep ordering based on the historical cursor, but re-check each candidate's
    # live publication and learner authorization before returning any navigation.
    candidates = await resume_candidate(
        repo,
        principal.tenant_id,
        principal.user_id,
        await repo.list_progress(principal.tenant_id, principal.user_id),
    )
    for item in candidates:
        if await ensure_published_access(
            agent, bearer, item.book_id, item.course_id, item.content_version_id
        ):
            return await resume_view(repo, principal.tenant_id, principal.user_id, item)
    return None


@router.delete("/resume", status_code=status.HTTP_204_NO_CONTENT, operation_id="resetResumeCursor")
async def reset_resume_cursor(
    principal: Annotated[Principal, Depends(get_current_principal)],
    key: Annotated[str, Header(alias="Idempotency-Key", min_length=1, max_length=255)],
    repo: Annotated[StudyRepository, Depends(study_repository)],
) -> Response:
    await repo.reset_cursor(principal.tenant_id, principal.user_id, key)
    return Response(status_code=status.HTTP_204_NO_CONTENT)


@router.put(
    "/study-status/memory-consent",
    response_model=StudyMemoryConsentView,
    operation_id="setStudyMemoryConsent",
)
async def set_study_memory_consent(
    body: StudyMemoryConsentRequest,
    principal: Annotated[Principal, Depends(get_current_principal)],
    repo: Annotated[StudyRepository, Depends(study_repository)],
) -> StudyMemoryConsentView:
    await repo.set_memory_consent(principal.tenant_id, principal.user_id, body.enabled)
    return StudyMemoryConsentView(enabled=body.enabled)


@router.get(
    "/study-status/memory-signals",
    response_model=tuple[StudyMemorySignalView, ...],
    operation_id="getStudyMemorySignals",
)
async def get_study_memory_signals(
    principal: Annotated[Principal, Depends(get_current_principal)],
    bearer: Annotated[str, Header(alias="Authorization")],
    repo: Annotated[StudyRepository, Depends(study_repository)],
    agent: Annotated[AgentCatalogClient, Depends(catalog)],
) -> tuple[StudyMemorySignalView, ...]:
    if not await repo.get_memory_consent(principal.tenant_id, principal.user_id):
        raise HTTPException(status_code=403, detail="study memory consent is disabled")
    progress = await _authorized_progress(repo, principal, bearer, agent)
    return tuple(memory_signal(item) for item in summarize_plans(progress))
