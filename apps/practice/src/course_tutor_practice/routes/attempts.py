"""Learner answer and give-up commands; protected answers only appear after release."""

from __future__ import annotations

import hashlib
import json
from typing import Annotated
from uuid import UUID

from fastapi import APIRouter, Depends, Header, HTTPException

from course_tutor_auth import Principal, get_current_principal
from course_tutor_contracts import AttemptFeedbackView, SubmitPracticeAnswerRequest
from course_tutor_practice.adapters.agent_client import AgentCatalogClient
from course_tutor_practice.application.evaluation import evaluate
from course_tutor_practice.domain.attempts import AttemptConflict, Evaluation, ExerciseMaterial
from course_tutor_practice.domain.policies import POLICY_VERSION, feedback
from course_tutor_practice.ports.study import StudyRepository
from course_tutor_practice.routes.study_dependencies import (
    catalog,
    ensure_published_access,
    rubric_evaluator,
    study_repository,
)
from course_tutor_shared import get_correlation_id

router = APIRouter(
    prefix="/v1/practice/sets/{set_id}/exercises/{exercise_id}", tags=["practice-attempts"]
)


def _digest(action: str, answer: str | bool | None) -> str:
    payload = json.dumps({"action": action, "answer": answer}, sort_keys=True, ensure_ascii=False)
    return hashlib.sha256(payload.encode()).hexdigest()


async def _material(
    repo: StudyRepository,
    principal: Principal,
    set_id: UUID,
    exercise_id: UUID,
    bearer: str,
    client: AgentCatalogClient,
) -> ExerciseMaterial:
    material = await repo.get_material(principal.tenant_id, principal.user_id, set_id, exercise_id)
    if material is None:
        raise HTTPException(status_code=404, detail="exercise not found")
    if not await ensure_published_access(
        client, bearer, material.book_id, material.course_id, material.content_version_id
    ):
        raise HTTPException(status_code=404, detail="exercise not found")
    return material


@router.post("/attempts", response_model=AttemptFeedbackView, operation_id="submitPracticeAnswer")
async def submit_practice_answer(
    set_id: UUID,
    exercise_id: UUID,
    body: SubmitPracticeAnswerRequest,
    principal: Annotated[Principal, Depends(get_current_principal)],
    bearer: Annotated[str, Header(alias="Authorization")],
    key: Annotated[str, Header(alias="Idempotency-Key", min_length=1, max_length=255)],
    repo: Annotated[StudyRepository, Depends(study_repository)],
    agent: Annotated[AgentCatalogClient, Depends(catalog)],
    evaluator: Annotated[object, Depends(rubric_evaluator)],
) -> AttemptFeedbackView:
    material = await _material(repo, principal, set_id, exercise_id, bearer, agent)
    digest = _digest("submit", body.answer)
    previous = await repo.get_attempts(principal.tenant_id, principal.user_id, exercise_id)
    replay = next((item for item in previous if item.idempotency_key == key), None)
    if replay is not None:
        if replay.request_digest != digest:
            raise HTTPException(
                status_code=409, detail="idempotency key conflicts with prior answer"
            )
        return feedback(material, replay)
    if (
        any(item.action == "give_up" or item.evaluation.correct is True for item in previous)
        or sum(item.action == "submit" for item in previous) >= 3
    ):
        raise HTTPException(status_code=409, detail="exercise is already complete")
    try:
        evaluation = await evaluate(material, body.answer, evaluator, get_correlation_id() or "")  # type: ignore[arg-type]
        attempt = await repo.record_attempt(
            material,
            action="submit",
            answer=body.answer,
            digest=digest,
            idempotency_key=key,
            evaluation=evaluation,
        )
    except ValueError as exc:
        status_code = 409 if isinstance(exc, AttemptConflict) else 422
        raise HTTPException(status_code=status_code, detail=str(exc)) from exc
    except RuntimeError as exc:
        raise HTTPException(status_code=503, detail="short-answer evaluation unavailable") from exc
    return feedback(material, attempt)


@router.post("/give-up", response_model=AttemptFeedbackView, operation_id="giveUpPracticeExercise")
async def give_up_practice_exercise(
    set_id: UUID,
    exercise_id: UUID,
    principal: Annotated[Principal, Depends(get_current_principal)],
    bearer: Annotated[str, Header(alias="Authorization")],
    key: Annotated[str, Header(alias="Idempotency-Key", min_length=1, max_length=255)],
    repo: Annotated[StudyRepository, Depends(study_repository)],
    agent: Annotated[AgentCatalogClient, Depends(catalog)],
) -> AttemptFeedbackView:
    material = await _material(repo, principal, set_id, exercise_id, bearer, agent)
    try:
        attempt = await repo.record_attempt(
            material,
            action="give_up",
            answer=None,
            digest=_digest("give_up", None),
            idempotency_key=key,
            evaluation=Evaluation(
                correct=False,
                score=0,
                provisional=False,
                evaluator="policy",
                evaluator_version=POLICY_VERSION,
            ),
        )
    except AttemptConflict as exc:
        raise HTTPException(status_code=409, detail=str(exc)) from exc
    return feedback(material, attempt)
