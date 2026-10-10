"""Deterministic study projection from immutable attempts and activity events."""

from __future__ import annotations

from dataclasses import dataclass
from datetime import datetime
from typing import Literal
from uuid import UUID

from course_tutor_contracts import StudySetProgressView
from course_tutor_practice.domain.attempts import AttemptRecord


@dataclass(frozen=True, slots=True)
class ActivityRecord:
    id: UUID
    set_id: UUID | None
    exercise_id: UUID | None
    event_type: str
    created_at: datetime


def project_set(
    *,
    set_id: UUID,
    study_plan_id: UUID,
    book_id: UUID,
    course_id: UUID,
    content_version_id: UUID,
    exercise_ids: tuple[UUID, ...],
    attempts: tuple[AttemptRecord, ...],
    activities: tuple[ActivityRecord, ...],
    module_id: UUID | None,
) -> StudySetProgressView:
    by_exercise: dict[UUID, list[AttemptRecord]] = {item: [] for item in exercise_ids}
    for attempt in attempts:
        if attempt.exercise_id in by_exercise:
            by_exercise[attempt.exercise_id].append(attempt)
    completed = 0
    correct = 0
    attempted = 0
    next_id = None
    for exercise_id in exercise_ids:
        records = by_exercise[exercise_id]
        if records:
            attempted += 1
        is_correct = any(item.evaluation.correct is True for item in records)
        is_done = is_correct or any(
            item.action == "give_up"
            or (item.evaluation.correct is False and item.attempt_number >= 3)
            for item in records
        )
        correct += int(is_correct)
        completed += int(is_done)
        if next_id is None and not is_done:
            next_id = exercise_id
    status: Literal["NOT_STARTED", "IN_PROGRESS", "COMPLETED"] = (
        "COMPLETED"
        if exercise_ids and completed == len(exercise_ids)
        else "IN_PROGRESS"
        if activities
        else "NOT_STARTED"
    )
    mastery = {str(module_id): round(correct / completed, 3)} if module_id and completed else {}
    return StudySetProgressView(
        practice_set_id=set_id,
        study_plan_id=study_plan_id,
        book_id=book_id,
        course_id=course_id,
        content_version_id=content_version_id,
        status=status,
        total_questions=len(exercise_ids),
        attempted_questions=attempted,
        completed_questions=completed,
        correct_questions=correct,
        next_exercise_id=next_id,
        latest_activity_at=max((item.created_at for item in activities), default=None),
        topic_mastery=mastery,
    )
