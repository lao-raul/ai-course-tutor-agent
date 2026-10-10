"""Objective grading and bounded provisional rubric evaluation."""

from __future__ import annotations

import unicodedata
from typing import Protocol

from course_tutor_contracts import QuestionType
from course_tutor_practice.domain.attempts import Evaluation, ExerciseMaterial

OBJECTIVE_VERSION = "objective-nfkc-v1"


class RubricEvaluator(Protocol):
    model_version: str

    async def score(
        self, *, answer: str, exemplar: str, criteria: tuple[str, ...], correlation_id: str
    ) -> tuple[float, ...]: ...


def _normalize(value: str) -> str:
    return " ".join(unicodedata.normalize("NFKC", value).casefold().split())


async def evaluate(
    material: ExerciseMaterial,
    answer: str | bool,
    evaluator: RubricEvaluator | None,
    correlation_id: str,
) -> Evaluation:
    question = material.view
    protected = material.protected_answer
    if question.type is QuestionType.TRUE_FALSE:
        if not isinstance(answer, bool):
            raise ValueError("true_false requires a boolean answer")
        correct = answer is protected["answer"]
    else:
        if not isinstance(answer, str) or not answer.strip():
            raise ValueError("this question requires a non-empty text answer")
        if question.type is QuestionType.MULTIPLE_CHOICE:
            if answer not in {option.id for option in question.options}:
                raise ValueError("answer must be an option ID")
            correct = answer == protected["correct_option_id"]
        elif question.type is QuestionType.FILL_IN_THE_BLANK:
            correct = _normalize(answer) in {
                _normalize(item) for item in protected["acceptable_answers"]
            }
        elif question.type is QuestionType.SHORT_ANSWER:
            if evaluator is None:
                raise RuntimeError("short-answer evaluator is unavailable")
            criteria = tuple(item.description for item in question.rubric)
            scores = await evaluator.score(
                answer=answer,
                exemplar=str(protected["exemplar_answer"]),
                criteria=criteria,
                correlation_id=correlation_id,
            )
            if len(scores) != len(criteria) or any(not 0 <= item <= 1 for item in scores):
                raise RuntimeError("short-answer evaluator returned invalid criterion scores")
            score = round(
                sum(
                    item.weight * value for item, value in zip(question.rubric, scores, strict=True)
                ),
                3,
            )
            return Evaluation(
                correct=score >= float(protected["pass_threshold"]),
                score=score,
                provisional=True,
                evaluator="rubric_llm",
                evaluator_version=evaluator.model_version,
            )
        else:  # pragma: no cover
            raise ValueError("unsupported question type")
    return Evaluation(
        correct=correct,
        score=float(correct),
        provisional=False,
        evaluator="deterministic",
        evaluator_version=OBJECTIVE_VERSION,
    )
