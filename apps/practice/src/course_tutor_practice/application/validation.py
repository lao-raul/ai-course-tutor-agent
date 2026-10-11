"""Deterministic gates before storing an immutable PracticeSet."""

from __future__ import annotations

import re
import unicodedata
from math import isfinite

from course_tutor_contracts import (
    ExerciseDraft,
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


def question_fingerprint(prompt: str) -> str:
    """Use the same duplicate key while collecting drafts and before persistence."""
    return _normalized(prompt)


def _keywords(text: str) -> set[str]:
    return {word for word in re.findall(r"[a-z]{3,}|[\u4e00-\u9fff]{2,}", _normalized(text))}


def _contains_answer(evidence: str, answer: str) -> bool:
    normalized = _normalized(answer)
    return len(normalized) >= 2 and normalized in _normalized(evidence)


def _is_metadata_question(prompt: str) -> bool:
    """Reject questions *about* navigation metadata, not those using it as context."""
    normalized = _normalized(prompt)
    if re.search(
        r"标题|课题|篇名|后记|编者|出版说明|"
        r"\b(?:title|heading|page number)\b",
        normalized,
    ) or re.search(
        r"(?:这|本|第\s*\d+\s*)页.{0,12}(?:叫什么|是什么活动|是哪(?:个|一)活动|是否出现)",
        normalized,
    ):
        return True
    heading = re.search(
        r"listen and say|listen and repeat|listen and point|look and say|read and write",
        normalized,
    )
    if heading is None:
        return False
    before = normalized[: heading.start()].rstrip(" \"'\u201c\u2018")
    after = normalized[heading.end() :].lstrip(" \"'\u201d\u2019")
    return bool(
        (
            re.search(r"(?:是|有|出现|包含|包括|叫|写着)$", before)
            and re.match(r"(?:(?:这个)?(?:活动|栏目|环节))?(?:吗|\?|\uff1f|$)", after)
        )
        or re.match(
            r"(?:是(?:什么|哪(?:个|一))(?:活动|栏目|环节)|叫什么|出现了?(?:吗|\?|\uff1f)|吗)",
            after,
        )
    )


def is_true_false_statement(prompt: str) -> bool:
    """A true/false exercise needs a complete claim, not a question or answer cue."""
    stem = prompt.strip()
    if not stem or stem.rstrip("。.!\uff01 ").endswith(("?", "\uff1f", ":", "\uff1a")):
        return False
    if re.search(r"(?:可能|应该)?会说(?:什么)?\s*$", stem):
        return False
    if re.search(r"(?:_{2,}|\uff3f{2,}|\.{2,}|…+)\s*$", stem):
        return False
    # Some models omit terminal punctuation from otherwise explicit questions.
    return not bool(
        re.search(
            r"(?:正确的回答|答案|英文表达|英语表达)(?:应该)?是(?:什么|哪(?:个|一)?句(?:话)?)"
            r"(?:[。.!\uff01\s]*)$",
            stem,
        )
        or re.match(
            r"(?i)^(?:what|who|where|why|how|which|is|are|do|does|can|could|"
            r"would|should)\b",
            stem,
        )
    )


def has_fill_in_blank_placeholder(prompt: str) -> bool:
    """A fill-in-the-blank prompt must show the learner where to type the answer."""
    return bool(re.search(r"_{2,}|\uff3f{2,}|\[\s*\]|[\uff08(]\s*[\uff09)]", prompt))


def has_unverified_dialogue_pairing(prompt: str) -> bool:
    """Reject a claimed question/answer pair of two quoted lines on one page."""
    question = re.search(r"询问|提问|有人问|对方问|问[\"'\u201c\u2018你他她]", prompt)
    answer = re.search(r"回答|答道|回应|回复|答复", prompt)
    quotes = tuple(
        re.finditer(r'[\u201c"]([^\u201d"]+)[\u201d"]|[\u2018]([^\u2019]+)[\u2019]', prompt)
    )
    if question and answer and len(quotes) >= 2:
        return question.start() < quotes[0].start() < answer.start() < quotes[1].start()
    normalized = _normalized(prompt)
    return bool(
        re.search(r"\b(?:ask|asked|asks|question)\b", normalized)
        and re.search(r"\b(?:answer|answered|reply|respond)\b", normalized)
        and len(quotes) >= 2
    )


def has_obvious_dialogue_answer_mismatch(prompt: str, answer: str) -> bool:
    """Catch greetings/yes-no replies used as answers to an object-name question."""
    stem = _normalized(prompt)
    if not re.search(r"询问|有人问|对方问|\b(?:ask|asked|asks)\b", stem):
        return False
    object_question = bool(
        re.search(r"这是什么|物品是什么|what(?:'s| is) this|是否是|是不是|is it", stem)
    )
    if not object_question:
        return False
    reply = _normalized(answer)
    if re.match(r"(?:hello|hi|goodbye|bye|thank you)\b", reply):
        return True
    return bool(
        re.search(r"这是什么|物品是什么|what(?:'s| is) this", stem)
        and re.match(r"(?:yes|no)\b", reply)
    )


def repair_grounding(draft: ExerciseDraft, evidence: PracticeEvidenceResponse) -> ExerciseDraft:
    """Repair mechanical citation/weight mistakes without inventing textbook answers.

    Only excerpts actually supplied to this inference call may be used to
    replace a citation. Unsupported answers still fail the normal validator.
    """
    by_id = {str(chunk.chunk_id): chunk for chunk in evidence.chunks}
    invalid_citation = any(citation not in by_id for citation in draft.evidence_citation_ids)
    if isinstance(draft, ShortAnswerExerciseDraft):
        if invalid_citation:
            return draft
        total = sum(item.weight for item in draft.rubric)
        if isfinite(total) and total > 0 and abs(total - 1) > 0.001:
            return draft.model_copy(
                update={
                    "rubric": tuple(
                        item.model_copy(update={"weight": item.weight / total})
                        for item in draft.rubric
                    )
                }
            )
        return draft
    answers: tuple[str, ...]
    if isinstance(draft, MultipleChoiceExerciseDraft):
        answers = (
            (next(option.text for option in draft.options if option.id == draft.correct_option_id),)
            if any(option.id == draft.correct_option_id for option in draft.options)
            else ()
        )
    elif isinstance(draft, FillInTheBlankExerciseDraft):
        answers = draft.acceptable_answers
    else:
        return draft
    if not answers:
        return draft
    if not invalid_citation:
        cited_text = " ".join(by_id[citation].text for citation in draft.evidence_citation_ids)
        if all(_contains_answer(cited_text, answer) for answer in answers):
            return draft
    supporting_ids: list[str] = []
    for answer in answers:
        source_id = next(
            (
                str(chunk.chunk_id)
                for chunk in evidence.chunks
                if _contains_answer(chunk.text, answer)
            ),
            None,
        )
        if source_id is None:
            return draft
        if source_id not in supporting_ids:
            supporting_ids.append(source_id)
    return draft.model_copy(update={"evidence_citation_ids": tuple(supporting_ids)})


def validate_batch(
    batch: GeneratedBatch,
    request: GeneratePracticeRequest,
    evidence: PracticeEvidenceResponse,
) -> None:
    if len(batch.exercises) != request.count:
        raise InvalidGeneration("count_mismatch")
    fingerprints: set[str] = set()
    for draft in batch.exercises:
        validate_draft(draft, request, evidence)
        fingerprint = question_fingerprint(draft.prompt)
        if fingerprint in fingerprints:
            raise InvalidGeneration("duplicate_question")
        fingerprints.add(fingerprint)


def validate_draft(
    draft: ExerciseDraft,
    request: GeneratePracticeRequest,
    evidence: PracticeEvidenceResponse,
) -> None:
    """Validate one candidate so a bad batch does not discard its good questions."""
    if _is_metadata_question(draft.prompt):
        raise InvalidGeneration("non_learning_question")
    if isinstance(draft, TrueFalseExerciseDraft) and not is_true_false_statement(draft.prompt):
        raise InvalidGeneration("invalid_true_false_statement")
    if isinstance(draft, FillInTheBlankExerciseDraft) and not has_fill_in_blank_placeholder(
        draft.prompt
    ):
        raise InvalidGeneration("missing_blank_placeholder")
    if has_unverified_dialogue_pairing(draft.prompt):
        raise InvalidGeneration("unsupported_dialogue_pairing")
    by_id = {str(chunk.chunk_id): chunk for chunk in evidence.chunks}
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
        if has_obvious_dialogue_answer_mismatch(draft.prompt, answer):
            raise InvalidGeneration("dialogue_answer_mismatch")
        if not _contains_answer(source, answer):
            raise InvalidGeneration("unsupported_answer")
        if _contains_answer(draft.prompt, answer):
            raise InvalidGeneration("answer_leakage")
    elif isinstance(draft, FillInTheBlankExerciseDraft):
        if any(
            has_obvious_dialogue_answer_mismatch(draft.prompt, answer)
            for answer in draft.acceptable_answers
        ):
            raise InvalidGeneration("dialogue_answer_mismatch")
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
