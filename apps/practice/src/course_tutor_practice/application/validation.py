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


_OCR_GARBAGE = re.compile(
    r"[�¢§®©]|\\\[_+\]+\]|\b[A-Za-z]{8,}\d+[A-Za-z]*\b|\b[A-Z]:\s*\|[A-Za-z]\b"
)


def has_obvious_ocr_garbage(text: str) -> bool:
    """Reject strong OCR artifacts, not ordinary textbook punctuation or math % signs."""
    return bool(_OCR_GARBAGE.search(text))


def has_unreadable_cloze_context(text: str) -> bool:
    """A single blank must not use merged turns or whole OCR page passages."""
    return (
        len(re.findall(r"\b[A-Z]:\s*", text)) > 1
        or len(re.findall(r"[.!?]", text)) > 3
        or bool(re.search(r"\b(?:and|or|the|a|an)\s+[.,!?]\s+[A-Za-z]", text, flags=re.IGNORECASE))
    )


def _keywords(text: str) -> set[str]:
    return {word for word in re.findall(r"[a-z]{3,}|[\u4e00-\u9fff]{2,}", _normalized(text))}


def _contains_answer(evidence: str, answer: str) -> bool:
    normalized = _normalized(answer)
    return len(normalized) >= 2 and normalized in _normalized(evidence)


def is_metadata_question(prompt: str) -> bool:
    """Reject questions *about* navigation metadata, not those using it as context."""
    normalized = _normalized(prompt)
    if (
        re.search(
            r"标题|课题|篇名|后记|编者|出版说明|学习目标|教学目标|"
            r"\b(?:title|heading|page number|learning objective)\b",
            normalized,
        )
        or re.search(
            r"(?:教材|课文|课本|文本)(?:中|里)(?:反复|多次|曾经|经常)?"
            r"(?:出现|提及|提到|包含|包括|收录)(?:了|过|的)?.{0,55}"
            r"(?:单词|词语|短语|表达|句子|指令|物品|事物)|"
            r"\b(?:appears?|occurs?|is found) in (?:the )?(?:textbook|text)\b",
            normalized,
        )
        or re.search(
            r"(?:这|本|第\s*\d+\s*)页.{0,12}(?:叫什么|是什么活动|是哪(?:个|一)活动|是否出现)",
            normalized,
        )
        or re.search(
            r"(?:教材|课本|课文).{0,80}(?:物品|事物|对象).{0,20}(?:包括|包含|有)",
            normalized,
        )
        or re.search(
            r"(?:教材|课本|课文)(?:中|里)?(?:明确)?要求.{0,25}(?:指向|指出)",
            normalized,
        )
        or re.search(
            r"(?:出现|属于|收录|位于).{0,24}(?:哪(?:个|种|一)|什么).{0,10}"
            r"(?:单元|模块|章节|活动|练习|栏目|环节)|"
            r"(?:单元|模块|章节|活动|练习|栏目|环节)(?:的)?"
            r"(?:名称|名字|标题)(?:是)?(?:什么|哪(?:个|一))|"
            r"(?:在哪(?:个|一)?)(?:单元|模块|章节)(?:中|里|出现|收录|学习)?|"
            r"(?:属于|是).{0,12}(?:哪(?:种|个|一)|什么)(?:活动|练习|栏目|环节)(?:类型)?",
            normalized,
        )
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


def is_unsupported_visual_question(prompt: str) -> bool:
    """Text-only evidence cannot establish what an unobserved picture depicts."""
    return bool(
        re.search(
            r"(?:在|看|观察|根据).{0,8}(?:图片|图画|插图|图中)|"
            r"(?:图片|图画|插图|画面)(?:中|里|上|所画|显示)|"
            r"\b(?:picture|image|illustration)\b",
            _normalized(prompt),
        )
    )


def has_unverified_pointing_scene(prompt: str) -> bool:
    """Text evidence for an instruction does not prove someone acted it out."""
    return bool(re.search(r"(?:有人|某人|说话者|人物|角色|他|她).{0,16}(?:指着|指向)", prompt))


def has_unverified_page_reference(prompt: str) -> bool:
    """PDF physical anchors are not necessarily the textbook's printed page numbers."""
    return bool(re.search(r"(?:课本|教材|课文)?第\s*\d+\s*页", prompt))


def has_unverified_family_coreference(prompt: str, source: str) -> bool:
    """Do not resolve he/she to a relative absent from the cited text."""
    if not re.search(
        r"(?:代词|\bpronoun\b).{0,12}(?<![A-Za-z])(?:he|she)(?![A-Za-z])"
        r".{0,16}(?:指代|refers? to)",
        prompt,
        re.I,
    ):
        return False
    family = {
        "父亲": "father",
        "爸爸": "father",
        "母亲": "mother",
        "妈妈": "mother",
        "祖父": "grandpa",
        "祖母": "grandma",
        "哥哥": "brother",
        "弟弟": "brother",
        "姐姐": "sister",
        "妹妹": "sister",
    }
    normalized_source = _normalized(source)
    return any(
        chinese in prompt and english not in normalized_source
        for chinese, english in family.items()
    )


def has_unsupported_spatial_claim(prompt: str, source: str) -> bool:
    """Example this/that utterances alone cannot prove a spatial relationship."""
    claim = _normalized(prompt)
    if not re.search(r"(?<![a-z])(?:this|that)(?![a-z])", claim):
        return False
    evidence = _normalized(source)
    near = r"近处|附近|\bnear(?:by)?\b"
    far = r"远处|远方|\bfar(?:away)?\b|\bdistant\b"
    return bool(
        (re.search(near, claim) and not re.search(near, evidence))
        or (re.search(far, claim) and not re.search(far, evidence))
    )


def _unverified_exhaustive_answer_terms(prompt: str, answer: str, rubric: str, source: str) -> bool:
    """An 'all items' answer may not list English terms absent from cited text."""
    if not re.search(
        r"列出(?:所有|全部)|(?:所有|全部).{0,20}(?:哪些|列出)|\blist all\b", _normalized(prompt)
    ):
        return False
    stopwords = {"and", "are", "for", "from", "into", "that", "the", "these", "this", "with"}
    answer_terms = {
        term
        for term in re.findall(r"[a-z]{3,}", _normalized(answer + " " + rubric))
        if term not in stopwords
    }
    source_terms = set(re.findall(r"[a-z]{3,}", _normalized(source)))
    return bool(answer_terms - source_terms)


def is_true_false_statement(prompt: str) -> bool:
    """A true/false exercise needs a complete claim, not a question or answer cue."""
    stem = prompt.strip()
    if not stem or stem.rstrip("。.!\uff01 ").endswith(("?", "\uff1f", ":", "\uff1a")):
        return False
    if re.match(
        r"^(?:(?:这句话|该句|上述句子)\s*(?:表明|说明|意味着)|"
        r"(?:this sentence|this statement)\s+(?:shows|means|indicates))",
        stem,
        re.IGNORECASE,
    ):
        return False
    if re.search(r"(?:可能|应该)?会说(?:什么)?\s*$", stem):
        return False
    if re.search(r"(?:_{2,}|\uff3f{2,}|\.{2,}|…+)\s*$", stem):
        return False
    if len(re.findall(r"[,\uff0c;\uff1b]", stem)) >= 2 and re.search(
        r"还有|以及|并且|同时|另外|\band also\b", stem, re.IGNORECASE
    ):
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
    return count_blank_placeholders(prompt) > 0


def count_blank_placeholders(prompt: str) -> int:
    """The current answer contract has one input, not independent fields per blank."""
    return len(re.findall(r"_{2,}|\uff3f{2,}|\[\s*\]|[\uff08(]\s*[\uff09)]", prompt))


def is_open_ended_fill_prompt(prompt: str) -> bool:
    """One blank cannot stand in for a second question or a list of answers."""
    normalized = _normalized(prompt)
    return bool(
        re.search(r"_{2,}.{0,35}(?:这句话|这句表达).{0,12}(?:意思|含义|表达什么)", normalized)
        or re.search(r"(?:哪些|列出).{0,30}(?:单词|词语|数字|身体部位)", normalized)
        or re.search(r"[?\uff1f]\s*_{2,}\s*[\u3002.?!\uff01\uff1f]*$", normalized)
        or re.search(r"[\"'\u201c\u2018]\s*_{2,}\s*[\"'\u201d\u2019]", normalized)
        or re.search(
            r"(?:句子|单词|短语|表达|指令)(?:是|为)\s*_{2,}\s*[\u3002.?!\uff01\uff1f]*$",
            normalized,
        )
    )


def requires_unprovided_followup(prompt: str, answer: str) -> bool:
    """A response cannot claim to ask back if the answer contains no question."""
    return bool(re.search(r"反问|ask back|ask in return", _normalized(prompt))) and not bool(
        re.search(r"[?\uff1f]", answer)
    )


def has_ambiguous_point_to_options(prompt: str, options: tuple[str, ...], source: str) -> bool:
    """A generic 'point to which word' item cannot have several cited correct options."""
    if not re.search(r"(?:指向|指出).{0,30}(?:哪个|哪一个|以下哪个)单词", prompt):
        return False
    if re.search(r"首先|第一个|最后|不在|不是|first|last|not", prompt, re.I):
        return False
    normalized_source = _normalized(source)
    supported = sum(
        bool(re.search(rf"(?<!\w){re.escape(_normalized(option))}(?!\w)", normalized_source))
        for option in options
        if len(option.strip()) >= 2
    )
    return supported > 1


def has_unsupported_quoted_fill_phrase(prompt: str, answers: tuple[str, ...], source: str) -> bool:
    """A quoted English phrase with a blank must exist verbatim once filled."""
    quoted = re.findall(r'["\u201c]([^"\u201d]*_{2,}[^"\u201d]*)["\u201d]', prompt)
    if not quoted:
        return False
    source_text = _normalized(source)
    for template in quoted:
        if re.search(r"[a-z]{2,}", template, re.I) and not any(
            _normalized(re.sub(r"_{2,}", answer, template)) in source_text for answer in answers
        ):
            return True
    return False


def has_unverified_injury_scene(prompt: str, source: str) -> bool:
    """Do not invent an injury/problem to connect unrelated textbook lines."""
    if not re.search(r"(?:如果|假如).{0,30}(?:受伤|疼痛|出现问题)", prompt):
        return False
    return not bool(
        re.search(r"受伤|疼痛|出现问题|\b(?:hurt|injured|pain|problem)\b", source, re.I)
    )


def has_ambiguous_repeated_dialogue_question(prompt: str, source: str) -> bool:
    """An identical spoken question repeated on a page needs an explicit turn index."""
    if not re.search(
        r"如何回答|怎么回答|回答(?:是|了|什么)|标准回答|正确回答|对应(?:的)?回答|如何回应|"
        r"\b(?:reply|answer)\b",
        prompt,
    ):
        return False
    if re.search(r"第一次|第二次|第一轮|第二轮|first time|second time", prompt, re.I):
        return False
    quoted_questions = re.findall(
        r"(?<![A-Za-z])['\"\u201c\u2018](.{1,120}?[?\uff1f])['\"\u201d\u2019]",
        prompt,
    )
    source_text = _normalized(source)
    return any(source_text.count(_normalized(question)) > 1 for question in quoted_questions)


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


def has_unverified_speaker_attribution(prompt: str, answer: str, source: str) -> bool:
    """A name in a greeting is the addressee, not evidence of who spoke next.

    OCR often flattens songs and speech bubbles into one line. Reject an item
    naming that addressee as the speaker of the immediately following answer
    unless the source separately labels the person as its speaker.
    """
    # A named speaker introduced only in a *later* scene cannot have spoken an
    # answer found solely in an earlier scene of the same flattened OCR chunk.
    for speaker in re.finditer(
        r"(?<![A-Za-z])(?:Mr|Mrs|Ms)\.?\s+[A-Z][a-z]+(?![A-Za-z])", prompt, re.I
    ):
        if not re.match(
            r".{0,4}(?:询问|提问|问(?:道|了)?|说(?:道|了)?|使用)",
            prompt[speaker.end() : speaker.end() + 12],
        ):
            continue
        name_in_source = re.search(re.escape(speaker.group()), source, re.I)
        answer_occurrences = list(re.finditer(re.escape(answer), source, re.I))
        if (
            name_in_source
            and answer_occurrences
            and all(item.end() < name_in_source.start() for item in answer_occurrences)
        ):
            return True
    for match in re.finditer(
        r"\b(?:hello|hi|good morning|good afternoon|good evening)[,! ]+"
        r"(?P<name>[A-Z][a-z]{2,})[.!?,]\s*(?P<reply>[^.!?]{2,80}[.!?])",
        source,
        re.I,
    ):
        name = match.group("name")
        speaker_mentions = re.finditer(
            rf"(?<![A-Za-z]){re.escape(name)}(?![A-Za-z]).{{0,35}}"
            r"(?:打招呼|询问|提问|问候|问(?:道|了|对方)?|说(?:道|了|的)?|使用)",
            prompt,
            re.I,
        )
        if not any(
            not re.search(
                r"(?:向|对|问)\s*$", prompt[max(0, mention.start() - 3) : mention.start()]
            )
            for mention in speaker_mentions
        ):
            continue
        if _normalized(answer).rstrip("?!.") != _normalized(match.group("reply")).rstrip("?!."):
            continue
        if re.search(
            rf"(?<![A-Za-z]){re.escape(name)}\s*[:\uff1a]\s*{re.escape(answer)}", source, re.I
        ):
            continue
        return True
    return False


def has_mismatched_named_reply(prompt: str, answer: str, source: str) -> bool:
    """A named addressee's reply must match the next printed dialogue turn."""
    if not re.search(r"(?:如何|怎么|怎样)?回答|回应|回复|\brespond\b|\breply\b", prompt, re.I):
        return False
    for name in re.findall(r"(?<![A-Za-z])[A-Z][a-z]{2,}(?![A-Za-z])", prompt):
        if name in {"Mr", "Mrs", "Ms"}:
            continue
        for question in re.finditer(rf"[^.!?]{{0,80}}\b{re.escape(name)}\s*\?", source, re.I):
            reply = re.match(r"\s*([^.!?]{1,100}[.!?])", source[question.end() :])
            if reply and _normalized(answer) != _normalized(reply.group(1)):
                return True
    return False


def has_incomplete_self_introduction(prompt: str, answer: str) -> bool:
    """A self-introduction expression must include the speaker's name.

    A question specifically about contraction or sentence structure can still
    test the isolated frame; a general "how did Sam introduce himself" cannot.
    """
    stem = _normalized(prompt)
    if not re.search(
        r"介绍自己|自我介绍|\bintroduc(?:e|ing) (?:oneself|yourself|himself|herself)\b",
        stem,
    ):
        return False
    if re.search(r"缩写|结构|句型|形式|\b(?:contraction|contracted form|sentence frame)\b", stem):
        return False
    return _normalized(answer).rstrip(".!?") in {"i'm", "im", "i am", "my name is"}


def has_misclassified_quantity_confirmation(prompt: str) -> bool:
    """'Nine girls?' confirms a proposed count; it does not ask for a number."""
    stem = _normalized(prompt)
    if not re.search(
        r"询问.{0,16}数量|\bask(?:ing)? (?:for|about) (?:the )?(?:number|quantity)\b",
        stem,
    ):
        return False
    if re.search(r"确认|核实|核对|是否|\bconfirm(?:ing)?\b", stem):
        return False
    return bool(
        re.search(
            r"['\u2018\u201c\"](?:one|two|three|four|five|six|seven|eight|nine|ten|\d+)"
            r"\s+[a-z]+s\?['\u2019\u201d\"]",
            stem,
        )
    )


def has_unsupported_distinction_claim(prompt: str, source: str) -> bool:
    """A chant repeating two nouns is not evidence that it teaches their difference."""
    claim = _normalized(prompt)
    if not re.search(r"通过.{0,16}重复.{0,16}(?:区分|辨别|区别)", claim):
        return False
    return not bool(
        re.search(
            r"区分|辨别|区别|不同|\b(?:different|difference|distinguish|contrast)\b",
            source,
            re.I,
        )
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
    if has_obvious_ocr_garbage(draft.prompt):
        raise InvalidGeneration("unreadable_ocr_prompt")
    if is_metadata_question(draft.prompt):
        raise InvalidGeneration("non_learning_question")
    if has_misclassified_quantity_confirmation(draft.prompt):
        raise InvalidGeneration("quantity_confirmation_mismatch")
    if is_unsupported_visual_question(draft.prompt):
        raise InvalidGeneration("unsupported_visual_claim")
    if has_unverified_pointing_scene(draft.prompt):
        raise InvalidGeneration("unsupported_visual_claim")
    if has_unverified_page_reference(draft.prompt):
        raise InvalidGeneration("unverified_page_reference")
    if isinstance(draft, TrueFalseExerciseDraft) and not is_true_false_statement(draft.prompt):
        raise InvalidGeneration("invalid_true_false_statement")
    if not isinstance(draft, FillInTheBlankExerciseDraft) and has_fill_in_blank_placeholder(
        draft.prompt
    ):
        raise InvalidGeneration("unexpected_blank_placeholder")
    if isinstance(draft, FillInTheBlankExerciseDraft) and not has_fill_in_blank_placeholder(
        draft.prompt
    ):
        raise InvalidGeneration("missing_blank_placeholder")
    if (
        isinstance(draft, FillInTheBlankExerciseDraft)
        and count_blank_placeholders(draft.prompt) != 1
    ):
        raise InvalidGeneration("multiple_blank_placeholders")
    if isinstance(draft, FillInTheBlankExerciseDraft) and is_open_ended_fill_prompt(draft.prompt):
        raise InvalidGeneration("open_ended_fill_prompt")
    if isinstance(draft, FillInTheBlankExerciseDraft) and has_unreadable_cloze_context(
        draft.prompt
    ):
        raise InvalidGeneration("unreadable_cloze_context")
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
    if has_unverified_family_coreference(draft.prompt, source):
        raise InvalidGeneration("unsupported_coreference")
    if (
        isinstance(draft, TrueFalseExerciseDraft)
        and any("/英语/" in by_id[citation].relative_path for citation in citation_ids)
        and not re.search(r"[A-Za-z]{2,}", draft.prompt)
    ):
        raise InvalidGeneration("non_learning_question")
    if has_unsupported_spatial_claim(draft.prompt, source):
        raise InvalidGeneration("unsupported_spatial_claim")
    if has_unsupported_distinction_claim(draft.prompt, source):
        raise InvalidGeneration("unsupported_distinction_claim")
    if has_ambiguous_repeated_dialogue_question(draft.prompt, source):
        raise InvalidGeneration("ambiguous_dialogue_answer")
    if has_unverified_injury_scene(draft.prompt, source):
        raise InvalidGeneration("unsupported_scenario")
    if isinstance(draft, MultipleChoiceExerciseDraft):
        ids = [option.id for option in draft.options]
        texts = [_normalized(option.text) for option in draft.options]
        if len(set(ids)) != len(ids) or len(set(texts)) != len(texts):
            raise InvalidGeneration("ambiguous_options")
        if has_ambiguous_point_to_options(
            draft.prompt, tuple(option.text for option in draft.options), source
        ):
            raise InvalidGeneration("ambiguous_options")
        if draft.correct_option_id not in ids:
            raise InvalidGeneration("invalid_answer")
        answer = next(
            option.text for option in draft.options if option.id == draft.correct_option_id
        )
        if has_incomplete_self_introduction(draft.prompt, answer):
            raise InvalidGeneration("incomplete_expression")
        if has_obvious_dialogue_answer_mismatch(draft.prompt, answer):
            raise InvalidGeneration("dialogue_answer_mismatch")
        if has_unverified_speaker_attribution(draft.prompt, answer, source):
            raise InvalidGeneration("unsupported_speaker_attribution")
        if has_mismatched_named_reply(draft.prompt, answer, source):
            raise InvalidGeneration("dialogue_answer_mismatch")
        if requires_unprovided_followup(draft.prompt, answer):
            raise InvalidGeneration("dialogue_answer_mismatch")
        if not _contains_answer(source, answer):
            raise InvalidGeneration("unsupported_answer")
        if _contains_answer(draft.prompt, answer):
            raise InvalidGeneration("answer_leakage")
    elif isinstance(draft, FillInTheBlankExerciseDraft):
        if has_unsupported_quoted_fill_phrase(draft.prompt, draft.acceptable_answers, source):
            raise InvalidGeneration("unsupported_fill_phrase")
        if any(
            has_obvious_dialogue_answer_mismatch(draft.prompt, answer)
            for answer in draft.acceptable_answers
        ):
            raise InvalidGeneration("dialogue_answer_mismatch")
        if any(
            has_unverified_speaker_attribution(draft.prompt, answer, source)
            for answer in draft.acceptable_answers
        ):
            raise InvalidGeneration("unsupported_speaker_attribution")
        if any(
            requires_unprovided_followup(draft.prompt, answer)
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
        if has_incomplete_self_introduction(draft.prompt, draft.exemplar_answer):
            raise InvalidGeneration("incomplete_expression")
        if has_unverified_speaker_attribution(draft.prompt, draft.exemplar_answer, source):
            raise InvalidGeneration("unsupported_speaker_attribution")
        if has_mismatched_named_reply(draft.prompt, draft.exemplar_answer, source):
            raise InvalidGeneration("dialogue_answer_mismatch")
        if requires_unprovided_followup(draft.prompt, draft.exemplar_answer):
            raise InvalidGeneration("dialogue_answer_mismatch")
        if abs(sum(item.weight for item in draft.rubric) - 1) > 0.001:
            raise InvalidGeneration("invalid_rubric")
        if _unverified_exhaustive_answer_terms(
            draft.prompt,
            draft.exemplar_answer,
            " ".join(item.description for item in draft.rubric),
            source,
        ):
            raise InvalidGeneration("unsupported_answer")
        if not (_keywords(draft.exemplar_answer) & _keywords(source)):
            raise InvalidGeneration("unsupported_answer")
        if _contains_answer(draft.prompt, draft.exemplar_answer):
            raise InvalidGeneration("answer_leakage")
    elif isinstance(draft, TrueFalseExerciseDraft):
        if not (_keywords(draft.prompt + " " + draft.rationale) & _keywords(source)):
            raise InvalidGeneration("unsupported_answer")
