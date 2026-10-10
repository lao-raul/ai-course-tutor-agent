"""Learner question reports with no answer material in the response."""

from __future__ import annotations

from typing import Annotated
from uuid import UUID

from fastapi import APIRouter, Depends, Header, HTTPException

from course_tutor_auth import Principal, get_current_principal
from course_tutor_contracts import ExerciseReportRequest, ExerciseReportView
from course_tutor_practice.adapters.agent_client import AgentCatalogClient
from course_tutor_practice.domain.attempts import AttemptConflict
from course_tutor_practice.ports.study import StudyRepository
from course_tutor_practice.routes.study_dependencies import (
    catalog,
    ensure_published_access,
    study_repository,
)

router = APIRouter(prefix="/v1/practice/exercises", tags=["practice-reports"])


@router.post(
    "/{exercise_id}/reports",
    response_model=ExerciseReportView,
    operation_id="reportPracticeExercise",
)
async def report_practice_exercise(
    exercise_id: UUID,
    body: ExerciseReportRequest,
    principal: Annotated[Principal, Depends(get_current_principal)],
    bearer: Annotated[str, Header(alias="Authorization")],
    key: Annotated[str, Header(alias="Idempotency-Key", min_length=1, max_length=255)],
    repo: Annotated[StudyRepository, Depends(study_repository)],
    agent: Annotated[AgentCatalogClient, Depends(catalog)],
) -> ExerciseReportView:
    material = await repo.find_material(principal.tenant_id, principal.user_id, exercise_id)
    if material is None or not await ensure_published_access(
        agent, bearer, material.book_id, material.course_id, material.content_version_id
    ):
        raise HTTPException(status_code=404, detail="exercise not found")
    try:
        return await repo.save_report(material, body.reason, body.detail, key)
    except AttemptConflict as exc:
        raise HTTPException(status_code=409, detail=str(exc)) from exc
