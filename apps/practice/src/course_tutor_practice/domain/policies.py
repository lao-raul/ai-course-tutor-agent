"""Answer-release and hint policy; never derives hints from protected answers."""

from __future__ import annotations

from typing import Literal

from course_tutor_contracts import (
    AnswerReleaseView,
    AttemptFeedbackView,
    PracticeLanguage,
    QuestionType,
)
from course_tutor_practice.domain.attempts import AttemptRecord, ExerciseMaterial

POLICY_VERSION = "three-incorrect-v1"

_HINTS_EN = {
    QuestionType.MULTIPLE_CHOICE: (
        "Review the cited textbook section before choosing an option.",
        "Compare each option with the wording and examples in the cited section.",
    ),
    QuestionType.TRUE_FALSE: (
        "Find the relevant statement in the cited textbook section.",
        "Check whether every part of the statement agrees with the cited section.",
    ),
    QuestionType.FILL_IN_THE_BLANK: (
        "Look at the context around the blank and the cited section.",
        "Check the grammar and exact term used in the cited textbook section.",
    ),
    QuestionType.SHORT_ANSWER: (
        "Review the visible rubric and the cited textbook section.",
        "Address each visible rubric criterion with evidence from the cited section.",
    ),
}

_HINTS_ZH = {
    QuestionType.MULTIPLE_CHOICE: (
        "先阅读引用的教材段落后再选择选项。",
        "逐一对照选项与教材中的表述和例子。",
    ),
    QuestionType.TRUE_FALSE: (
        "在引用的教材段落中找到相关表述。",
        "检查题目中的每一部分是否都与教材一致。",
    ),
    QuestionType.FILL_IN_THE_BLANK: (
        "结合空格前后的语境及引用的教材段落思考。",
        "检查语法并寻找教材使用的准确词语。",
    ),
    QuestionType.SHORT_ANSWER: (
        "对照可见的评分标准和引用的教材段落。",
        "尝试用教材证据逐项回应评分标准。",
    ),
}


def released(attempt: AttemptRecord) -> bool:
    return attempt.action == "give_up" or (
        attempt.evaluation.correct is False and attempt.attempt_number >= 3
    )


def feedback(material: ExerciseMaterial, attempt: AttemptRecord) -> AttemptFeedbackView:
    release = None
    if released(attempt):
        protected = material.protected_answer
        answer: str | bool | tuple[str, ...]
        if "correct_option_id" in protected:
            answer = str(protected["correct_option_id"])
        elif "answer" in protected:
            answer = bool(protected["answer"])
        elif "acceptable_answers" in protected:
            answer = tuple(str(item) for item in protected["acceptable_answers"])
        else:
            answer = str(protected["exemplar_answer"])
        release = AnswerReleaseView(
            answer=answer,
            rationale=material.rationale,
            evidence_citation_ids=material.view.evidence_citation_ids,
        )
    hint = None
    if (
        attempt.action == "submit"
        and attempt.evaluation.correct is False
        and attempt.attempt_number in {1, 2}
    ):
        index = attempt.attempt_number - 1
        chinese = _HINTS_ZH[material.view.type][index]
        english = _HINTS_EN[material.view.type][index]
        hint = (
            chinese
            if material.view.language is PracticeLanguage.ZH
            else english
            if material.view.language is PracticeLanguage.EN
            else f"{chinese} / {english}"
        )
    outcome: Literal["correct", "incorrect", "provisional", "gave_up"] = (
        "gave_up"
        if attempt.action == "give_up"
        else "provisional"
        if attempt.evaluation.provisional
        else "correct"
        if attempt.evaluation.correct
        else "incorrect"
    )
    return AttemptFeedbackView(
        id=attempt.id,
        exercise_id=attempt.exercise_id,
        attempt_number=attempt.attempt_number,
        outcome=outcome,
        correct=attempt.evaluation.correct,
        score=attempt.evaluation.score,
        provisional=attempt.evaluation.provisional,
        hint=hint,
        released_answer=release,
        evaluator=attempt.evaluation.evaluator,
        evaluator_version=attempt.evaluation.evaluator_version,
        created_at=attempt.created_at,
    )
