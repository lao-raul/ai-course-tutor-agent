"""Safe resume ordering and compact consent-gated memory signal shaping."""

from __future__ import annotations

from typing import Literal
from uuid import UUID

from course_tutor_contracts import (
    ResumeView,
    StudyMemorySignalView,
    StudyPlanProgressView,
    StudySetProgressView,
)
from course_tutor_practice.ports.study import StudyRepository


async def resume_candidate(
    repository: StudyRepository,
    tenant_id: UUID,
    user_id: UUID,
    progress: tuple[StudySetProgressView, ...],
) -> tuple[StudySetProgressView, ...]:
    cursor_set_id, cleared = await repository.get_cursor(tenant_id, user_id)
    if cleared:
        return ()
    return tuple(
        sorted(
            (item for item in progress if item.next_exercise_id is not None),
            key=lambda item: (
                item.practice_set_id == cursor_set_id,
                item.latest_activity_at.isoformat() if item.latest_activity_at else "",
                str(item.practice_set_id),
            ),
            reverse=True,
        )
    )


async def resume_view(
    repository: StudyRepository,
    tenant_id: UUID,
    user_id: UUID,
    item: StudySetProgressView,
) -> ResumeView:
    assert item.next_exercise_id is not None
    attempts = await repository.get_attempts(tenant_id, user_id, item.next_exercise_id)
    return ResumeView(
        practice_set_id=item.practice_set_id,
        study_plan_id=item.study_plan_id,
        book_id=item.book_id,
        course_id=item.course_id,
        content_version_id=item.content_version_id,
        exercise_id=item.next_exercise_id,
        attempt_number=len([record for record in attempts if record.action == "submit"]),
        released=False,
    )


def summarize_plans(items: tuple[StudySetProgressView, ...]) -> tuple[StudyPlanProgressView, ...]:
    grouped: dict[UUID, list[StudySetProgressView]] = {}
    for item in items:
        grouped.setdefault(item.study_plan_id, []).append(item)
    result = []
    for plan_id, sets in grouped.items():
        total = sum(item.total_questions for item in sets)
        attempted = sum(item.attempted_questions for item in sets)
        completed = sum(item.completed_questions for item in sets)
        correct = sum(item.correct_questions for item in sets)
        status: Literal["NOT_STARTED", "IN_PROGRESS", "COMPLETED"] = (
            "COMPLETED"
            if total and completed == total
            else "IN_PROGRESS"
            if attempted
            else "NOT_STARTED"
        )
        topic_counts: dict[str, tuple[int, int]] = {}
        for item in sets:
            for module_id in item.topic_mastery:
                prior_correct, prior_completed = topic_counts.get(module_id, (0, 0))
                topic_counts[module_id] = (
                    prior_correct + item.correct_questions,
                    prior_completed + item.completed_questions,
                )
        result.append(
            StudyPlanProgressView(
                study_plan_id=plan_id,
                book_id=sets[0].book_id,
                status=status,
                practice_set_count=len(sets),
                total_questions=total,
                attempted_questions=attempted,
                completed_questions=completed,
                correct_questions=correct,
                latest_activity_at=max(
                    (item.latest_activity_at for item in sets if item.latest_activity_at),
                    default=None,
                ),
                topic_mastery={
                    module_id: round(counts[0] / counts[1], 3)
                    for module_id, counts in topic_counts.items()
                    if counts[1]
                },
            )
        )
    return tuple(result)


def memory_signal(item: StudyPlanProgressView) -> StudyMemorySignalView:
    ratio = item.correct_questions / item.completed_questions if item.completed_questions else 0
    band: Literal["starting", "developing", "confident"] = (
        "confident"
        if ratio >= 0.8 and item.completed_questions
        else "developing"
        if item.completed_questions
        else "starting"
    )
    return StudyMemorySignalView(
        book_id=item.book_id,
        study_plan_id=item.study_plan_id,
        completed_questions=item.completed_questions,
        total_questions=item.total_questions,
        mastery_band=band,
    )
