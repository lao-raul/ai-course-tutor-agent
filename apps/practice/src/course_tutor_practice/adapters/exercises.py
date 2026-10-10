"""Separate learner presentation data from protected answer material."""

from __future__ import annotations

import hashlib
from typing import Any
from uuid import UUID

from pydantic import TypeAdapter

from course_tutor_contracts import (
    ExerciseDraft,
    ExerciseView,
    FillInTheBlankExerciseDraft,
    MultipleChoiceExerciseDraft,
    ShortAnswerExerciseDraft,
    TrueFalseExerciseDraft,
)

_VIEW_ADAPTER: TypeAdapter[ExerciseView] = TypeAdapter(ExerciseView)


def split_exercise_draft(
    draft: ExerciseDraft, exercise_id: UUID, ordinal: int
) -> tuple[dict[str, Any], dict[str, Any], str, str, ExerciseView]:
    common: dict[str, Any] = {
        "id": str(exercise_id),
        "ordinal": ordinal,
        "type": draft.type.value,
        "prompt": draft.prompt,
        "difficulty": draft.difficulty.value,
        "language": draft.language.value,
        "evidence_citation_ids": list(draft.evidence_citation_ids),
    }
    protected: dict[str, Any]
    if isinstance(draft, MultipleChoiceExerciseDraft):
        common["options"] = [option.model_dump(mode="json") for option in draft.options]
        protected = {"correct_option_id": draft.correct_option_id}
    elif isinstance(draft, TrueFalseExerciseDraft):
        protected = {"answer": draft.answer}
    elif isinstance(draft, FillInTheBlankExerciseDraft):
        protected = {"acceptable_answers": list(draft.acceptable_answers)}
    elif isinstance(draft, ShortAnswerExerciseDraft):
        common["rubric"] = [item.model_dump(mode="json") for item in draft.rubric]
        protected = {
            "exemplar_answer": draft.exemplar_answer,
            "pass_threshold": draft.pass_threshold,
        }
    else:  # pragma: no cover - the discriminated union is exhaustive
        raise TypeError(f"unsupported exercise draft {type(draft)!r}")
    fingerprint = hashlib.sha256(
        f"{draft.type.value}\0{draft.prompt.strip().casefold()}".encode()
    ).hexdigest()
    return common, protected, draft.rationale, fingerprint, _VIEW_ADAPTER.validate_python(common)


def exercise_view_from_storage(presentation: dict[str, Any]) -> ExerciseView:
    return _VIEW_ADAPTER.validate_python(presentation)
