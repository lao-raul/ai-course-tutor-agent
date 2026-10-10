"""Deterministic gates before storing an immutable PracticeSet."""

from __future__ import annotations

import re
import unicodedata

from course_tutor_contracts import (
    FillInTheBlankExerciseDraft,
    GeneratePracticeRequest,
    MultipleChoiceExerciseDraft,
    PracticeEvidenceResponse,
    ShortAnswerExerciseDraft,
    TrueFalseExerciseDraft,
)
from course_tutor_practice.generation.schemas import GeneratedBatch


class InvalidGeneration(ValueError):
    """A safe error code; never carries textbook text or model output."""

    def __init__(self, code: str) -> None:
        super().__init__(code)
        self.code = code


def _normalized(text: str) -> str:
    return " ".join(unicodedata.normalize("NFKC", text).casefold().split())


def _keywords(text: str) -> set[str]:
    return {word for word in re.findall(r"[a-z]{3,}|[\u4e00-\u9fff]{2,}", _normalized(text))}


def _contains_answer(evidence: str, answer: str) -> bool:
    normalized = _normalized(answer)
    return len(normalized) >= 2 and normalized in _normalized(evidence)


def validate_batch(
    batch: GeneratedBatch,
    request: GeneratePracticeRequest,
    evidence: PracticeEvidenceResponse,
) -> None:
    if len(batch.exercises) != request.count:
        raise InvalidGeneration("count_mismatch")
    by_id = {str(chunk.chunk_id): chunk for chunk in evidence.chunks}
    fingerprints: set[str] = set()
    for draft in batch.exercises:
        if draft.type not in request.question_types:
            raise InvalidGeneration("type_mismatch")
        if draft.language != request.language or draft.difficulty != request.difficulty:
            raise InvalidGeneration("request_mismatch")
        citation_ids = draft.evidence_citation_ids
        if not citation_ids or len(citation_ids) != len(set(citation_ids)):
            raise InvalidGeneration("invalid_citations")
        if any(citation not in by_id for citation in citation_ids):
            raise InvalidGeneration("invalid_citations")
        source = " ".join(by_id[citation].text for citation in citation_ids)
        if not source.strip():
            raise InvalidGeneration("insufficient_evidence")
        fingerprint = _normalized(draft.prompt)
        if fingerprint in fingerprints:
            raise InvalidGeneration("duplicate_question")
        fingerprints.add(fingerprint)
        if isinstance(draft, MultipleChoiceExerciseDraft):
            ids = [option.id for option in draft.options]
            texts = [_normalized(option.text) for option in draft.options]
            if len(set(ids)) != len(ids) or len(set(texts)) != len(texts):
                raise InvalidGeneration("ambiguous_options")
            if draft.correct_option_id not in ids:
                raise InvalidGeneration("invalid_answer")
            answer = next(
                option.text for option in draft.options if option.id == draft.correct_option_id
            )
            if not _contains_answer(source, answer):
                raise InvalidGeneration("unsupported_answer")
            if _contains_answer(draft.prompt, answer):
                raise InvalidGeneration("answer_leakage")
        elif isinstance(draft, FillInTheBlankExerciseDraft):
            if len({_normalized(answer) for answer in draft.acceptable_answers}) != len(
                draft.acceptable_answers
            ):
                raise InvalidGeneration("ambiguous_answers")
            if any(not _contains_answer(source, answer) for answer in draft.acceptable_answers):
                raise InvalidGeneration("unsupported_answer")
            if any(_contains_answer(draft.prompt, answer) for answer in draft.acceptable_answers):
                raise InvalidGeneration("answer_leakage")
        elif isinstance(draft, ShortAnswerExerciseDraft):
            if abs(sum(item.weight for item in draft.rubric) - 1) > 0.001:
                raise InvalidGeneration("invalid_rubric")
            if not (_keywords(draft.exemplar_answer) & _keywords(source)):
                raise InvalidGeneration("unsupported_answer")
            if _contains_answer(draft.prompt, draft.exemplar_answer):
                raise InvalidGeneration("answer_leakage")
        elif isinstance(draft, TrueFalseExerciseDraft):
            if not (_keywords(draft.prompt + " " + draft.rationale) & _keywords(source)):
                raise InvalidGeneration("unsupported_answer")
