"""Immutable learner attempt records and protected evaluation inputs."""

from __future__ import annotations

from dataclasses import dataclass
from datetime import datetime
from typing import Any
from uuid import UUID

from course_tutor_contracts import ExerciseView


@dataclass(frozen=True, slots=True)
class ExerciseMaterial:
    tenant_id: UUID
    user_id: UUID
    set_id: UUID
    study_plan_id: UUID
    book_id: UUID
    course_id: UUID
    content_version_id: UUID
    exercise_id: UUID
    view: ExerciseView
    protected_answer: dict[str, Any]
    rationale: str


@dataclass(frozen=True, slots=True)
class Evaluation:
    correct: bool | None
    score: float | None
    provisional: bool
    evaluator: str
    evaluator_version: str


@dataclass(frozen=True, slots=True)
class AttemptRecord:
    id: UUID
    tenant_id: UUID
    user_id: UUID
    set_id: UUID
    exercise_id: UUID
    attempt_number: int
    action: str
    idempotency_key: str
    answer: str | bool | None
    request_digest: str
    evaluation: Evaluation
    created_at: datetime


class AttemptConflict(ValueError):
    """An idempotency key was reused with different input or an item is closed."""
