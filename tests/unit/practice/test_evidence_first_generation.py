"""Evidence extraction and independent semantic audit are both required to publish."""

from __future__ import annotations

import json
from uuid import uuid4

import pytest
from course_tutor_practice_worker.evidence_first import (
    EvidenceFirstGenerationExecutor,
    TextbookFact,
    _answer_key,
    _answer_uses_fact,
    _draft_answer_keys,
    _has_unresolved_color_context,
    _repair_fill_from_fact,
    _select_cloze_fact,
    _usable_facts,
)

from course_tutor_contracts import (
    FillInTheBlankExerciseDraft,
    GeneratePracticeRequest,
    PracticeLanguage,
    QuestionType,
    RubricCriterion,
)
from course_tutor_practice.generation.errors import GenerationFailure
from course_tutor_practice.generation.objectives import answer_expression_keys
from course_tutor_practice.generation.schemas import (
    GeneratedBatch,
    GenerationContext,
    GenerationObjective,
)
from tests.unit.practice.test_grounded_generation import EvidenceStub, _draft, _evidence, _job


def test_reviewed_color_questions_require_unique_context() -> None:
    assert _has_unresolved_color_context("Now it's ____.", "Now it's blue. Now it's yellow.")
    assert _has_unresolved_color_context(
        "这顶帽子的颜色是什么", "It's a yellow cap. It's a red cap."
    )
    assert not _has_unresolved_color_context(
        "Translate 'yellow cap'.", "It's a yellow cap. It's a red cap."
    )
    assert not _has_unresolved_color_context("What color is the cap?", "It's a yellow cap.")


class StructuredStub:
    model = "test-model"

    def __init__(self, facts: str, draft: str, verdict: str) -> None:
        self.facts = facts
        self.draft = draft
        self.verdict = verdict
        self.calls: list[str] = []
        self.structured_messages: list[list[dict[str, str]]] = []
        self.question_messages: list[list[dict[str, str]]] = []

    async def generate_structured_json(
        self, messages, seed, correlation_id, *, schema, schema_name, temperature
    ):  # type: ignore[no-untyped-def]
        self.calls.append(schema_name)
        self.structured_messages.append(messages)
        assert correlation_id == "corr"
        assert schema["type"] == "object"
        if schema_name == "hiruzen_evidence_facts_v1":
            return self.facts
        assert schema_name == "hiruzen_semantic_verdict_v1"
        return self.verdict

    async def generate_json(self, messages, seed, correlation_id, *, count, temperature):  # type: ignore[no-untyped-def]
        self.calls.append("question")
        self.question_messages.append(messages)
        assert count == 1
        assert "MANDATORY FACT CARD" in messages[1]["content"]
        return self.draft


def test_answer_key_normalizes_typographic_apostrophes_and_punctuation() -> None:
    assert _answer_key("I'm fine, thank you.") == _answer_key("I\u2019m fine thank you!")
    assert _answer_key("head") == ""
    assert _answer_key("elephant") == ""


def _fact_json(
    citation_id: str, *, quote: str = "Hello is a greeting.", answer: str = "Hello"
) -> str:
    return json.dumps(
        {
            "facts": [
                {
                    "citation_id": citation_id,
                    "source_quote": quote,
                    "learning_objective": "Identify Hello as a greeting",
                    "answer_phrase": answer,
                }
            ]
        }
    )


def _verdict_json(*, answer_matches_question: bool = True) -> str:
    return json.dumps(
        {
            "fact_supported": True,
            "question_tests_fact": True,
            "answer_matches_question": answer_matches_question,
            "unambiguous": True,
            "distinct_objective": True,
        }
    )


def test_short_answer_cannot_combine_two_quoted_expressions() -> None:
    citation_id = uuid4()
    fact = TextbookFact(
        citation_id=citation_id,
        source_quote="Point to your head. This is my head.",
        learning_objective="Understand pointing to your head",
        answer_phrase="Point to your head.",
    )
    draft = _draft(QuestionType.SHORT_ANSWER, PracticeLanguage.EN, str(citation_id))
    draft = draft.model_copy(
        update={
            "exemplar_answer": "Point to your head. This is my head.",
            "rubric": (
                RubricCriterion(description="Say 'Point to your head. This is my head.'", weight=1),
            ),
        }
    )
    assert not _answer_uses_fact(draft, fact)


def test_published_short_answer_cannot_repeat_a_prior_reply_as_prefix() -> None:
    draft = _draft(QuestionType.SHORT_ANSWER, PracticeLanguage.EN, str(uuid4()))
    draft = draft.model_copy(update={"exemplar_answer": "I'm fine, thank you. And how are you?"})
    assert _draft_answer_keys(draft) & answer_expression_keys("I'm fine, thank you.")


@pytest.mark.asyncio
async def test_fact_extraction_rejects_obvious_ocr_garbage() -> None:
    _, job = await _job(GeneratePracticeRequest(count=1))
    evidence = _evidence(job)
    noisy_quote = "POOLE Listen and say. 3% MY §=Here's your cake."
    chunk = evidence.chunks[0].model_copy(update={"text": noisy_quote})
    assert (
        _usable_facts(_fact_json(str(chunk.chunk_id), quote=noisy_quote, answer="cake"), (chunk,))
        == ()
    )


@pytest.mark.asyncio
async def test_fact_extraction_skips_repeated_self_assessment_footer() -> None:
    _, job = await _job(GeneratePracticeRequest(count=1))
    evidence = _evidence(job)
    chunk = evidence.chunks[0].model_copy(
        update={"text": "Good morning, Sam. I can do this. I can do this."}
    )
    assert (
        _usable_facts(
            _fact_json(str(chunk.chunk_id), quote="I can do this.", answer="I can do this"),
            (chunk,),
        )
        == ()
    )


def test_open_ended_fill_is_repaired_from_exact_source_quote() -> None:
    citation_id = uuid4()
    fact = TextbookFact(
        citation_id=citation_id,
        source_quote="This is my father.",
        learning_objective="Name the father in a family introduction",
        answer_phrase="father",
    )
    draft = _draft(QuestionType.FILL_IN_THE_BLANK, PracticeLanguage.ZH, str(citation_id))
    assert isinstance(draft, FillInTheBlankExerciseDraft)
    draft = draft.model_copy(update={"prompt": "英语表达是____\uff1f"})
    repaired = _repair_fill_from_fact(draft, fact, PracticeLanguage.ZH)
    assert repaired is not None
    assert repaired.prompt == "补全教材原句\uff1a\u201cThis is my ____.\u201d"
    assert repaired.acceptable_answers == ("father",)


def test_fill_repair_omits_pdf_heading_marker_from_student_prompt() -> None:
    citation_id = uuid4()
    fact = TextbookFact(
        citation_id=citation_id,
        source_quote="# My name is Panpan.",
        learning_objective="State one's own name",
        answer_phrase="Panpan",
    )
    draft = _draft(QuestionType.FILL_IN_THE_BLANK, PracticeLanguage.ZH, str(citation_id))
    assert isinstance(draft, FillInTheBlankExerciseDraft)
    repaired = _repair_fill_from_fact(draft, fact, PracticeLanguage.ZH)
    assert repaired is not None
    assert repaired.prompt == "补全教材原句\uff1a\u201cMy name is ____.\u201d"


def test_fill_repair_rejects_answer_without_source_context() -> None:
    citation_id = uuid4()
    fact = TextbookFact(
        citation_id=citation_id,
        source_quote="Say Hello!",
        learning_objective="Recognize the greeting Hello",
        answer_phrase="Hello",
    )
    draft = _draft(QuestionType.FILL_IN_THE_BLANK, PracticeLanguage.EN, str(citation_id))
    assert isinstance(draft, FillInTheBlankExerciseDraft)
    assert _repair_fill_from_fact(draft, fact, PracticeLanguage.EN) is None


def test_fill_repair_rejects_merged_page_length_quote() -> None:
    fact = TextbookFact(
        citation_id=uuid4(),
        source_quote=(
            "Here's your present. Happy birthday, Sam. Here's your cake. "
            "Oh! It's a pen. Thank you! I'm nine!"
        ),
        learning_objective="Use birthday phrases",
        answer_phrase="Thank you",
    )
    draft = _draft(QuestionType.FILL_IN_THE_BLANK, PracticeLanguage.EN, str(fact.citation_id))
    assert isinstance(draft, FillInTheBlankExerciseDraft)
    assert _repair_fill_from_fact(draft, fact, PracticeLanguage.EN) is None


def test_long_page_quote_can_yield_one_exact_printed_sentence() -> None:
    fact = TextbookFact(
        citation_id=uuid4(),
        source_quote=(
            "Here's your present. Happy birthday, Sam. Here's your cake. "
            "Oh! It's a pen. Thank you! I'm nine!"
        ),
        learning_objective="Use a birthday greeting",
        answer_phrase="Happy birthday, Sam.",
    )
    selected = _select_cloze_fact(fact)
    assert selected is not None
    assert selected.answer_phrase == "birthday"
    draft = _draft(QuestionType.FILL_IN_THE_BLANK, PracticeLanguage.EN, str(fact.citation_id))
    assert isinstance(draft, FillInTheBlankExerciseDraft)
    repaired = _repair_fill_from_fact(draft, selected, PracticeLanguage.EN)
    assert repaired is not None
    assert repaired.prompt == "Complete the textbook sentence: \u201cHappy ____, Sam.\u201d"


def test_whole_sentence_fill_answer_can_select_exact_content_word() -> None:
    fact = TextbookFact(
        citation_id=uuid4(),
        source_quote="Is it a monster?",
        learning_objective="Recognize a monster identification question",
        answer_phrase="Is it a monster?",
    )
    selected = _select_cloze_fact(fact)
    assert selected is not None
    assert selected.answer_phrase == "monster"
    draft = _draft(QuestionType.FILL_IN_THE_BLANK, PracticeLanguage.EN, str(fact.citation_id))
    assert isinstance(draft, FillInTheBlankExerciseDraft)
    repaired = _repair_fill_from_fact(draft, selected, PracticeLanguage.EN)
    assert repaired is not None
    assert repaired.prompt == "Complete the textbook sentence: \u201cIs it a ____?\u201d"


@pytest.mark.asyncio
async def test_single_question_multi_page_scope_gets_extra_fact_extraction_passes() -> None:
    request = GeneratePracticeRequest(count=1)
    _, job = await _job(request)
    evidence = _evidence(job)
    first = evidence.chunks[0]
    chunks = tuple(first.model_copy(update={"chunk_id": uuid4()}) for _ in range(3))
    grouped = evidence.model_copy(update={"chunks": chunks})
    stub = StructuredStub(_fact_json(str(chunks[0].chunk_id)), "{}", "{}")
    executor = EvidenceFirstGenerationExecutor(EvidenceStub(grouped), stub)
    facts = await executor._extract_facts(job, GenerationContext(grouped), 11)
    assert len(facts) == 1
    assert stub.calls == ["hiruzen_evidence_facts_v1"] * 4


@pytest.mark.asyncio
async def test_one_question_collects_alternatives_after_first_three_facts() -> None:
    request = GeneratePracticeRequest(count=1)
    _, job = await _job(request)
    evidence = _evidence(job)
    citation_id = str(evidence.chunks[0].chunk_id)

    def fact(quote: str, objective: str, answer: str) -> dict[str, str]:
        return {
            "citation_id": citation_id,
            "source_quote": quote,
            "learning_objective": objective,
            "answer_phrase": answer,
        }

    greeting = "Hello is a greeting."
    encounter = "Children say Hello when they meet a friend."
    responses = [
        json.dumps(
            {
                "facts": [
                    fact(greeting, "Identify Hello as a greeting", "Hello"),
                    fact(encounter, "Recognize friend meeting context", "friend"),
                    fact(encounter, "Identify the child subject", "Children"),
                ]
            }
        ),
        json.dumps({"facts": [fact(encounter, "Recognize the action verb say", "say")]}),
    ]

    class SequencedFactStub(StructuredStub):
        async def generate_structured_json(
            self, messages, seed, correlation_id, *, schema, schema_name, temperature
        ):  # type: ignore[no-untyped-def]
            assert schema_name == "hiruzen_evidence_facts_v1"
            self.calls.append(schema_name)
            return responses.pop(0)

    stub = SequencedFactStub("", "", "")
    executor = EvidenceFirstGenerationExecutor(EvidenceStub(evidence), stub)
    facts = await executor._extract_facts(job, GenerationContext(evidence), 11)
    assert len(facts) == 4
    assert len(stub.calls) == 2


@pytest.mark.asyncio
async def test_fill_generation_uses_fact_quote_as_cloze() -> None:
    request = GeneratePracticeRequest(
        count=1,
        language=PracticeLanguage.EN,
        question_types=(QuestionType.FILL_IN_THE_BLANK,),
    )
    _, job = await _job(request)
    evidence = _evidence(job)
    citation_id = str(evidence.chunks[0].chunk_id)
    draft = _draft(QuestionType.FILL_IN_THE_BLANK, PracticeLanguage.EN, citation_id)
    assert isinstance(draft, FillInTheBlankExerciseDraft)
    draft = draft.model_copy(update={"prompt": "Which greeting is used? ____"})
    stub = StructuredStub(
        _fact_json(citation_id),
        GeneratedBatch(exercises=(draft,)).model_dump_json(),
        _verdict_json(),
    )
    executor = EvidenceFirstGenerationExecutor(EvidenceStub(evidence), stub)
    outcome = await executor.generate(job, await executor.retrieve(job))
    accepted = outcome.drafts[0]
    assert isinstance(accepted, FillInTheBlankExerciseDraft)
    assert accepted.prompt == "Complete the textbook sentence: \u201c____ is a greeting.\u201d"
    assert accepted.acceptable_answers == ("Hello",)
    assert "one meaningful word" in stub.structured_messages[0][0]["content"]


@pytest.mark.asyncio
async def test_large_request_extracts_from_separate_chunk_groups() -> None:
    request = GeneratePracticeRequest(count=6)
    _, job = await _job(request)
    evidence = _evidence(job)
    first = evidence.chunks[0]
    chunks = tuple(first.model_copy(update={"chunk_id": uuid4()}) for _ in range(6))
    grouped_evidence = evidence.model_copy(update={"chunks": chunks})
    stub = StructuredStub(_fact_json(str(chunks[0].chunk_id)), "{}", "{}")
    executor = EvidenceFirstGenerationExecutor(EvidenceStub(grouped_evidence), stub)
    facts = await executor._extract_facts(job, GenerationContext(grouped_evidence), 11)
    assert len(facts) == 1
    assert len(stub.structured_messages) == 4  # two groups, two bounded passes
    first_group = stub.structured_messages[0][1]["content"]
    second_group = stub.structured_messages[1][1]["content"]
    assert str(chunks[0].chunk_id) in first_group
    assert str(chunks[5].chunk_id) not in first_group
    assert str(chunks[5].chunk_id) in second_group


@pytest.mark.asyncio
async def test_evidence_first_accepts_only_after_semantic_verdict() -> None:
    request = GeneratePracticeRequest(
        count=1,
        language=PracticeLanguage.EN,
        question_types=(QuestionType.MULTIPLE_CHOICE,),
    )
    _, job = await _job(request)
    evidence = _evidence(job)
    chunk = evidence.chunks[0]
    evidence = evidence.model_copy(
        update={
            "chunks": (
                chunk.model_copy(
                    update={"text": chunk.text + " Unrelated scene: Your name, please? Sam!"}
                ),
            )
        }
    )
    citation_id = str(evidence.chunks[0].chunk_id)
    draft = _draft(QuestionType.MULTIPLE_CHOICE, PracticeLanguage.EN, citation_id)
    stub = StructuredStub(
        _fact_json(citation_id),
        GeneratedBatch(exercises=(draft,)).model_dump_json(),
        _verdict_json(),
    )
    executor = EvidenceFirstGenerationExecutor(EvidenceStub(evidence), stub)
    outcome = await executor.generate(job, await executor.retrieve(job))
    assert outcome.drafts == (draft,)
    assert outcome.objectives == (GenerationObjective("Identify Hello as a greeting", ""),)
    assert outcome.prompt_version.startswith("hiruzen-evidence-first")
    assert "Unrelated scene" not in stub.question_messages[0][1]["content"]
    verdict_messages = [
        item
        for item in stub.structured_messages
        if "independent textbook question auditor" in item[0]["content"]
    ]
    assert verdict_messages
    assert "Unrelated scene" in verdict_messages[0][1]["content"]


@pytest.mark.asyncio
async def test_exact_count_question_can_fallback_only_after_independent_audit() -> None:
    request = GeneratePracticeRequest(
        count=1,
        language=PracticeLanguage.ZH,
        question_types=(QuestionType.TRUE_FALSE,),
    )
    _, job = await _job(request)
    evidence = _evidence(job)
    chunk = evidence.chunks[0].model_copy(
        update={"relative_path": "小学/英语/book.pdf", "text": "How many dogs? How many cats?"}
    )
    evidence = evidence.model_copy(update={"chunks": (chunk,)})
    stub = StructuredStub('{"facts": []}', "{}", _verdict_json())
    executor = EvidenceFirstGenerationExecutor(EvidenceStub(evidence), stub)
    outcome = await executor.generate(job, await executor.retrieve(job))
    assert len(outcome.drafts) == 1
    assert "How many dogs?" in outcome.drafts[0].prompt
    assert stub.calls.count("question") == 0
    assert "hiruzen_semantic_verdict_v1" in stub.calls


@pytest.mark.asyncio
async def test_count_question_fallback_never_bypasses_failed_semantic_audit() -> None:
    request = GeneratePracticeRequest(count=1, question_types=(QuestionType.TRUE_FALSE,))
    _, job = await _job(request)
    evidence = _evidence(job)
    chunk = evidence.chunks[0].model_copy(
        update={"relative_path": "小学/英语/book.pdf", "text": "How many dogs?"}
    )
    evidence = evidence.model_copy(update={"chunks": (chunk,)})
    stub = StructuredStub('{"facts": []}', "{}", _verdict_json(answer_matches_question=False))
    executor = EvidenceFirstGenerationExecutor(EvidenceStub(evidence), stub)
    with pytest.raises(GenerationFailure, match="insufficient_evidence"):
        await executor.generate(job, await executor.retrieve(job))


@pytest.mark.asyncio
async def test_prior_answer_expression_is_skipped_before_question_generation() -> None:
    request = GeneratePracticeRequest(
        count=1,
        language=PracticeLanguage.EN,
        question_types=(QuestionType.MULTIPLE_CHOICE,),
    )
    _, job = await _job(request)
    evidence = _evidence(job)
    chunk = evidence.chunks[0].model_copy(
        update={
            "text": (
                "How are you? I'm fine, thank you. "
                "Hello is a greeting. Children say Hello when they meet a friend."
            )
        }
    )
    evidence = evidence.model_copy(update={"chunks": (chunk,)})
    facts = json.dumps(
        {
            "facts": [
                {
                    "citation_id": str(chunk.chunk_id),
                    "source_quote": "How are you? I'm fine, thank you.",
                    "learning_objective": "Answer a question about how you feel",
                    "answer_phrase": "I'm fine, thank you.",
                },
                {
                    "citation_id": str(chunk.chunk_id),
                    "source_quote": "Hello is a greeting.",
                    "learning_objective": "Identify Hello as a greeting",
                    "answer_phrase": "Hello",
                },
            ]
        }
    )
    draft = _draft(QuestionType.MULTIPLE_CHOICE, PracticeLanguage.EN, str(chunk.chunk_id))
    stub = StructuredStub(
        facts,
        GeneratedBatch(exercises=(draft,)).model_dump_json(),
        _verdict_json(),
    )

    async def read_prior(_job: object) -> tuple[GenerationObjective, ...]:
        return (
            GenerationObjective(
                "Give the usual response to How are you", _answer_key("I'm fine, thank you")
            ),
        )

    executor = EvidenceFirstGenerationExecutor(EvidenceStub(evidence), stub, read_prior)
    outcome = await executor.generate(job, await executor.retrieve(job))
    assert outcome.objectives[0].learning_objective == "Identify Hello as a greeting"
    assert stub.calls.count("question") == 1
    assert "Give the usual response to How are you" not in stub.structured_messages[0][1]["content"]
    assert "Give the usual response to How are you" in stub.structured_messages[-1][1]["content"]
    assert stub.calls == [
        "hiruzen_evidence_facts_v1",
        "hiruzen_evidence_facts_v1",
        "question",
        "hiruzen_semantic_verdict_v1",
    ]


@pytest.mark.asyncio
async def test_full_exemplar_prefix_cannot_reuse_prior_reply() -> None:
    request = GeneratePracticeRequest(
        count=1,
        language=PracticeLanguage.EN,
        question_types=(QuestionType.SHORT_ANSWER,),
    )
    _, job = await _job(request)
    evidence = _evidence(job)
    chunk = evidence.chunks[0].model_copy(
        update={"text": "How are you? I'm fine, thank you. And how are you?"}
    )
    evidence = evidence.model_copy(update={"chunks": (chunk,)})
    facts = _fact_json(
        str(chunk.chunk_id),
        quote="I'm fine, thank you. And how are you?",
        answer="And how are you?",
    )
    draft = _draft(QuestionType.SHORT_ANSWER, PracticeLanguage.EN, str(chunk.chunk_id))
    draft = draft.model_copy(
        update={
            "prompt": "How should the learner answer and ask back?",
            "exemplar_answer": "I'm fine, thank you. And how are you?",
            "rubric": (
                RubricCriterion(description="Use 'And how are you?' to ask back", weight=1),
            ),
        }
    )
    stub = StructuredStub(
        facts, GeneratedBatch(exercises=(draft,)).model_dump_json(), _verdict_json()
    )

    async def read_prior(_job: object) -> tuple[GenerationObjective, ...]:
        return (
            GenerationObjective("Answer a well-being inquiry", _answer_key("I'm fine, thank you.")),
        )

    executor = EvidenceFirstGenerationExecutor(EvidenceStub(evidence), stub, read_prior)
    with pytest.raises(GenerationFailure, match="validation_failed"):
        await executor.generate(job, await executor.retrieve(job))
    assert stub.calls.count("question") == 3
    assert "hiruzen_semantic_verdict_v1" not in stub.calls


@pytest.mark.asyncio
async def test_visual_only_draft_gets_two_bounded_extra_text_only_repairs() -> None:
    request = GeneratePracticeRequest(
        count=1,
        language=PracticeLanguage.EN,
        question_types=(QuestionType.SHORT_ANSWER,),
    )
    _, job = await _job(request)
    evidence = _evidence(job)
    chunk = evidence.chunks[0].model_copy(update={"text": "It's a yellow cap."})
    evidence = evidence.model_copy(update={"chunks": (chunk,)})
    draft = _draft(QuestionType.SHORT_ANSWER, PracticeLanguage.EN, str(chunk.chunk_id))
    draft = draft.model_copy(update={"prompt": "What do you see in the picture?"})
    stub = StructuredStub(
        _fact_json(str(chunk.chunk_id), quote="It's a yellow cap.", answer="yellow cap"),
        GeneratedBatch(exercises=(draft,)).model_dump_json(),
        _verdict_json(),
    )
    executor = EvidenceFirstGenerationExecutor(EvidenceStub(evidence), stub)
    with pytest.raises(GenerationFailure, match="validation_failed"):
        await executor.generate(job, await executor.retrieve(job))
    assert stub.calls.count("question") == 5
    assert "hiruzen_semantic_verdict_v1" not in stub.calls


@pytest.mark.asyncio
async def test_rejected_fact_does_not_pin_all_later_facts_to_one_type() -> None:
    request = GeneratePracticeRequest(
        count=1,
        language=PracticeLanguage.EN,
        question_types=(QuestionType.TRUE_FALSE, QuestionType.MULTIPLE_CHOICE),
    )
    _, job = await _job(request)
    evidence = _evidence(job)
    citation_id = str(evidence.chunks[0].chunk_id)
    facts = json.dumps(
        {
            "facts": [
                {
                    "citation_id": citation_id,
                    "source_quote": "Hello is a greeting.",
                    "learning_objective": "Identify Hello as a greeting",
                    "answer_phrase": "Hello",
                },
                {
                    "citation_id": citation_id,
                    "source_quote": "Children say Hello when they meet a friend.",
                    "learning_objective": "Identify a greeting for friends",
                    "answer_phrase": "Hello",
                },
            ]
        }
    )
    draft = _draft(QuestionType.MULTIPLE_CHOICE, PracticeLanguage.EN, citation_id)

    class RotatingStub(StructuredStub):
        question_messages: list[list[dict[str, str]]]

        def __init__(self) -> None:
            super().__init__(
                facts, GeneratedBatch(exercises=(draft,)).model_dump_json(), _verdict_json()
            )
            self.question_messages = []

        async def generate_json(self, messages, seed, correlation_id, *, count, temperature):  # type: ignore[no-untyped-def]
            self.question_messages.append(messages)
            if len(self.question_messages) <= 3:
                return "{}"
            return await super().generate_json(
                messages, seed, correlation_id, count=count, temperature=temperature
            )

    stub = RotatingStub()
    executor = EvidenceFirstGenerationExecutor(EvidenceStub(evidence), stub)
    outcome = await executor.generate(job, await executor.retrieve(job))
    assert outcome.drafts == (draft,)
    assert "allowed types=true_false" in stub.question_messages[0][1]["content"]
    assert "allowed types=multiple_choice" in stub.question_messages[3][1]["content"]


@pytest.mark.asyncio
async def test_evidence_first_rejects_answer_question_mismatch() -> None:
    request = GeneratePracticeRequest(
        count=1,
        language=PracticeLanguage.EN,
        question_types=(QuestionType.MULTIPLE_CHOICE,),
    )
    _, job = await _job(request)
    evidence = _evidence(job)
    citation_id = str(evidence.chunks[0].chunk_id)
    draft = _draft(QuestionType.MULTIPLE_CHOICE, PracticeLanguage.EN, citation_id)
    stub = StructuredStub(
        _fact_json(citation_id),
        GeneratedBatch(exercises=(draft,)).model_dump_json(),
        _verdict_json(answer_matches_question=False),
    )
    executor = EvidenceFirstGenerationExecutor(EvidenceStub(evidence), stub)
    with pytest.raises(GenerationFailure, match="validation_failed"):
        await executor.generate(job, await executor.retrieve(job))
    assert stub.calls[-1] == "hiruzen_semantic_verdict_v1"


@pytest.mark.asyncio
async def test_evidence_first_rejects_fabricated_quote_before_question() -> None:
    request = GeneratePracticeRequest(count=1)
    _, job = await _job(request)
    evidence = _evidence(job)
    stub = StructuredStub(
        _fact_json(str(evidence.chunks[0].chunk_id), quote="Hello is a magic unicorn."),
        "{}",
        "{}",
    )
    executor = EvidenceFirstGenerationExecutor(EvidenceStub(evidence), stub)
    with pytest.raises(GenerationFailure, match="insufficient_evidence"):
        await executor.generate(job, await executor.retrieve(job))
    assert stub.calls == ["hiruzen_evidence_facts_v1", "hiruzen_evidence_facts_v1"]


@pytest.mark.asyncio
async def test_evidence_first_requires_answer_from_chosen_fact() -> None:
    request = GeneratePracticeRequest(
        count=1,
        language=PracticeLanguage.EN,
        question_types=(QuestionType.MULTIPLE_CHOICE,),
    )
    _, job = await _job(request)
    evidence = _evidence(job)
    citation_id = str(evidence.chunks[0].chunk_id)
    draft = _draft(QuestionType.MULTIPLE_CHOICE, PracticeLanguage.EN, citation_id)
    stub = StructuredStub(
        _fact_json(citation_id, answer="greeting"),
        GeneratedBatch(exercises=(draft,)).model_dump_json(),
        _verdict_json(),
    )
    executor = EvidenceFirstGenerationExecutor(EvidenceStub(evidence), stub)
    with pytest.raises(GenerationFailure, match="validation_failed"):
        await executor.generate(job, await executor.retrieve(job))
    assert stub.calls == [
        "hiruzen_evidence_facts_v1",
        "hiruzen_evidence_facts_v1",
        "question",
        "question",
        "question",
    ]
