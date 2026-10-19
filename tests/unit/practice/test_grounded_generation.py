"""Grounded generation contracts without NAS, database or live inference."""

from __future__ import annotations

import json
from datetime import UTC, datetime, timedelta
from uuid import uuid4

import httpx
import jwt
import pytest
from course_tutor_practice_worker.grounded import GroundedGenerationExecutor
from course_tutor_practice_worker.worker import PracticeWorker
from pydantic import ValidationError

from course_tutor_auth import Principal
from course_tutor_auth.practice_delegation import (
    issue_practice_delegation,
    verify_practice_delegation,
)
from course_tutor_contracts import (
    ChoiceOption,
    ChunkClass,
    FillInTheBlankExerciseDraft,
    GeneratePracticeRequest,
    MultipleChoiceExerciseDraft,
    PracticeDifficulty,
    PracticeEvidenceChunk,
    PracticeEvidenceResponse,
    PracticeLanguage,
    QuestionType,
    RubricCriterion,
    ShortAnswerExerciseDraft,
    TrueFalseExerciseDraft,
)
from course_tutor_contracts.enums import AccessLabel, AnchorType, UserRole
from course_tutor_practice.adapters.inference import OpenAICompatiblePracticeInference
from course_tutor_practice.adapters.memory_repository import InMemoryPracticeRepository
from course_tutor_practice.application.generation import GenerationService
from course_tutor_practice.application.validation import (
    InvalidGeneration,
    has_fill_in_blank_placeholder,
    has_incomplete_self_introduction,
    has_misclassified_quantity_confirmation,
    has_mismatched_named_reply,
    has_obvious_dialogue_answer_mismatch,
    has_unsupported_distinction_claim,
    has_unsupported_spatial_claim,
    has_unverified_dialogue_pairing,
    has_unverified_family_coreference,
    has_unverified_page_reference,
    has_unverified_pointing_scene,
    has_unverified_speaker_attribution,
    is_metadata_question,
    is_open_ended_fill_prompt,
    is_true_false_statement,
    repair_grounding,
    requires_unprovided_followup,
    validate_draft,
)
from course_tutor_practice.domain import ModuleRecord, StudyPlanRecord
from course_tutor_practice.generation.schemas import GeneratedBatch
from course_tutor_shared import Settings


def _principal() -> Principal:
    return Principal(
        user_id=uuid4(),
        tenant_id=uuid4(),
        role=UserRole.STUDENT,
        access_label=AccessLabel.ENROLLED,
        subject="learner",
    )


async def _job(
    request: GeneratePracticeRequest,
) -> tuple[InMemoryPracticeRepository, object]:
    repository = InMemoryPracticeRepository()
    principal = _principal()
    plan = StudyPlanRecord(
        id=uuid4(),
        tenant_id=principal.tenant_id,
        book_id=uuid4(),
        course_id=uuid4(),
        course_run_id=uuid4(),
        content_version_id=uuid4(),
        name="FLTRP Grade 3",
        revision=1,
        modules=(ModuleRecord(id=uuid4(), ordinal=0, title="Unit 1 Hello"),),
    )
    await repository.save_study_plan(plan)
    job, _ = await GenerationService(repository).submit(principal, plan, request, "key", "corr")
    return repository, job


def _evidence(job: object) -> PracticeEvidenceResponse:
    return PracticeEvidenceResponse(
        generation_id=job.id,
        book_id=job.book_id,
        course_id=job.course_id,
        content_version_id=job.content_version_id,
        retrieval_trace_id=uuid4(),
        retrieval_policy_version="fixture-v1",
        allowed_content_classes=(ChunkClass.CONTENT,),
        solution_release_after_incorrect_attempts=3,
        chunks=(
            PracticeEvidenceChunk(
                chunk_id=uuid4(),
                source_id=uuid4(),
                text="Unit 1: Hello is a greeting. Children say Hello when they meet a friend.",
                relative_path="grade-3-english.pdf",
                anchor_type=AnchorType.PAGE,
                anchor_value="4",
                chunk_class=ChunkClass.CONTENT,
                score=0.93,
            ),
        ),
    )


class EvidenceStub:
    def __init__(self, response: PracticeEvidenceResponse) -> None:
        self.response = response
        self.calls = 0
        self.last_request = None

    async def retrieve(self, request, token, correlation_id):  # type: ignore[no-untyped-def]
        self.calls += 1
        self.last_request = request
        claims = verify_practice_delegation(
            token, Settings().practice_delegation_secret.get_secret_value()
        )
        assert claims.generation_id == request.generation_id == self.response.generation_id
        assert claims.content_version_id == request.content_version_id
        assert correlation_id == "corr"
        return self.response


@pytest.mark.asyncio
async def test_selected_outline_node_is_sent_to_agent_evidence() -> None:
    repository = InMemoryPracticeRepository()
    principal = _principal()
    module = ModuleRecord(id=uuid4(), ordinal=0, title="Unit 1 I'm Sam", outline_node_id="ol_sam")
    plan = StudyPlanRecord(
        id=uuid4(),
        tenant_id=principal.tenant_id,
        book_id=uuid4(),
        course_id=uuid4(),
        course_run_id=uuid4(),
        content_version_id=uuid4(),
        name="FLTRP Grade 3",
        revision=1,
        modules=(module,),
    )
    await repository.save_study_plan(plan)
    job, _ = await GenerationService(repository).submit(
        principal,
        plan,
        GeneratePracticeRequest(count=1, module_id=module.id),
        "outline-key",
        "corr",
    )
    stub = EvidenceStub(_evidence(job))
    await GroundedGenerationExecutor(stub, InferenceStub([])).retrieve(job)
    assert job.request_payload["_outline_node_id"] == "ol_sam"
    assert stub.last_request.outline_node_id == "ol_sam"


@pytest.mark.asyncio
async def test_twenty_question_job_requests_fact_headroom_from_agent() -> None:
    _, job = await _job(GeneratePracticeRequest(count=20))
    stub = EvidenceStub(_evidence(job))
    await GroundedGenerationExecutor(stub, InferenceStub([])).retrieve(job)
    assert stub.last_request.limit == 40


class InferenceStub:
    model = "fake-practice-model"

    def __init__(self, outputs: list[str]) -> None:
        self.outputs = outputs
        self.calls = 0
        self.messages: list[list[dict[str, str]]] = []
        self.seeds: list[int] = []
        self.temperatures: list[float] = []

    async def generate_json(
        self,
        messages: list[dict[str, str]],
        seed: int,
        correlation_id: str,
        *,
        count: int,
        temperature: float,
    ) -> str:
        assert seed >= 0
        assert count >= 1
        assert correlation_id == "corr"
        self.messages.append(messages)
        self.seeds.append(seed)
        self.temperatures.append(temperature)
        result = self.outputs[self.calls]
        self.calls += 1
        return result


def _draft(kind: QuestionType, language: PracticeLanguage, citation: str):
    common = {
        "difficulty": PracticeDifficulty.STANDARD,
        "language": language,
        "evidence_citation_ids": (citation,),
        "rationale": "The cited text says Hello is a greeting.",
    }
    if kind is QuestionType.MULTIPLE_CHOICE:
        return MultipleChoiceExerciseDraft(
            prompt="Which word is the greeting in Unit 1?",
            options=(ChoiceOption(id="a", text="Hello"), ChoiceOption(id="b", text="Goodbye")),
            correct_option_id="a",
            **common,
        )
    if kind is QuestionType.TRUE_FALSE:
        return TrueFalseExerciseDraft(
            prompt="Unit 1 teaches a greeting for friends.", answer=True, **common
        )
    if kind is QuestionType.FILL_IN_THE_BLANK:
        return FillInTheBlankExerciseDraft(
            prompt="Fill in the greeting: ____!", acceptable_answers=("Hello",), **common
        )
    return ShortAnswerExerciseDraft(
        prompt="Describe the greeting used when meeting a friend.",
        exemplar_answer="Hello is a greeting.",
        rubric=(RubricCriterion(description="Names the greeting Hello", weight=1),),
        **common,
    )


@pytest.mark.asyncio
@pytest.mark.parametrize("kind", (QuestionType.MULTIPLE_CHOICE, QuestionType.SHORT_ANSWER))
async def test_non_fill_question_cannot_show_answer_blank(kind: QuestionType) -> None:
    request = GeneratePracticeRequest(count=1, language=PracticeLanguage.EN, question_types=(kind,))
    _, job = await _job(request)
    evidence = _evidence(job)
    draft = _draft(kind, PracticeLanguage.EN, str(evidence.chunks[0].chunk_id))
    draft = draft.model_copy(update={"prompt": "What greeting is used here? ____"})
    with pytest.raises(InvalidGeneration) as failure:
        validate_draft(draft, request, evidence)
    assert failure.value.code == "unexpected_blank_placeholder"


@pytest.mark.parametrize(
    "prompt",
    (
        "当有人递给你生日礼物并说\u201c____\u201d时\uff0c这句话是在表达什么\uff1f",
        "需要识别哪些身体部位的英语单词\uff1f____",
        "当需要向他人打招呼时\uff0c应该使用哪句英语问候语\uff1f____",
        "当向他人介绍自己的父亲时\uff0c可以使用'____'来介绍。",
        "对方最可能说的英语表达是____\uff1f",
    ),
)
def test_open_ended_fill_prompt_is_rejected(prompt: str) -> None:
    assert is_open_ended_fill_prompt(prompt)


def test_claimed_followup_requires_question_in_answer() -> None:
    assert requires_unprovided_followup("应该用哪句话来回答并反问对方\uff1f____", "I'm fine too.")
    assert not requires_unprovided_followup(
        "应该用哪句话来回答并反问对方\uff1f____", "I'm fine. And how are you?"
    )


@pytest.mark.parametrize(
    "prompt",
    (
        "这页的标题是 Listen and say 吗?",
        "Is the title of this page Listen and say?",
        "第 12 页的标题是什么?",
        "这页有 Listen and say 吗?",
        "Listen and say 是什么活动?",
        "根据教材内容, 'One, two, three, four.' 这句话出现在哪个单元?",
        "根据教材内容, 'One, two, three, four.' 这句话属于哪种活动类型?",
        "根据教材内容, 'One, two, three, four.' 这句话出现在哪个听力练习环节中?",
        "'One, two, three, four.' 这个序列出现的单元名称是什么?",
        "Pen and pencil 是教材中出现的短语。",
        "Pen and pencil是教材中反复出现的短语。",
        "教材中出现了'Point to the desk.'这一指令。",
        "The phrase Pen and pencil appears in the textbook.",
    ),
)
@pytest.mark.asyncio
async def test_activity_heading_questions_are_rejected(prompt: str) -> None:
    request = GeneratePracticeRequest(count=1)
    _, job = await _job(request)
    evidence = _evidence(job)
    draft = _draft(QuestionType.TRUE_FALSE, PracticeLanguage.ZH, str(evidence.chunks[0].chunk_id))
    with pytest.raises(InvalidGeneration, match="non_learning_question"):
        validate_draft(draft.model_copy(update={"prompt": prompt}), request, evidence)


@pytest.mark.parametrize(
    "prompt",
    (
        "在 Listen and say 对话中，Hello 用于问候朋友。",  # noqa: RUF001
        "这句话出现在练习中，用于问候朋友。",  # noqa: RUF001
        "根据教材中出现的对话，Hello 用于问候朋友。",  # noqa: RUF001
    ),
)
@pytest.mark.asyncio
async def test_navigation_reference_is_not_a_metadata_question(prompt: str) -> None:
    request = GeneratePracticeRequest(count=1)
    _, job = await _job(request)
    evidence = _evidence(job)
    draft = _draft(QuestionType.TRUE_FALSE, PracticeLanguage.ZH, str(evidence.chunks[0].chunk_id))
    validate_draft(draft.model_copy(update={"prompt": prompt}), request, evidence)


@pytest.mark.asyncio
async def test_unverified_printed_page_reference_is_rejected() -> None:
    request = GeneratePracticeRequest(count=1)
    _, job = await _job(request)
    evidence = _evidence(job)
    draft = _draft(QuestionType.TRUE_FALSE, PracticeLanguage.ZH, str(evidence.chunks[0].chunk_id))
    with pytest.raises(InvalidGeneration, match="unverified_page_reference"):
        validate_draft(
            draft.model_copy(update={"prompt": "根据教材第 12 页的对话, Hello 用于问候朋友。"}),
            request,
            evidence,
        )


@pytest.mark.asyncio
async def test_near_far_rule_requires_textual_support_not_only_example_questions() -> None:
    request = GeneratePracticeRequest(count=1)
    _, job = await _job(request)
    original = _evidence(job)
    excerpt = "What's this? It's a cat. What's that? It's a bag."
    evidence = original.model_copy(
        update={"chunks": (original.chunks[0].model_copy(update={"text": excerpt}),)}
    )
    prompt = "'What's this?'用于询问近处的物体, 而'What's that?'用于询问远处的物体。"
    assert has_unsupported_spatial_claim(prompt, excerpt)
    draft = _draft(QuestionType.TRUE_FALSE, PracticeLanguage.ZH, str(evidence.chunks[0].chunk_id))
    with pytest.raises(InvalidGeneration, match="unsupported_spatial_claim"):
        validate_draft(draft.model_copy(update={"prompt": prompt}), request, evidence)
    explicit = "Use What's this for nearby things and What's that for distant things."
    assert not has_unsupported_spatial_claim(prompt, explicit)
    single = "使用指示代词this询问近处物体时, 回答应使用It's加该物体的名称。"
    assert has_unsupported_spatial_claim(single, excerpt)


@pytest.mark.parametrize(
    "prompt",
    (
        "补全教材原句\uff1a\u201cA: Is it a monster? B: No, it ____.\u201d",
        "补全教材原句\uff1a\u201cOh, ____ cat kite. Your cat or . your kite?\u201d",
        "补全教材原句\uff1a\u201cHere's your present. Happy birthday, Sam. "
        "Here's your cake. Oh! It's a pen. ____ 1,2, 3. I'm nine!\u201d",
    ),
)
@pytest.mark.asyncio
async def test_unreadable_cloze_is_rejected_before_persistence(prompt: str) -> None:
    request = GeneratePracticeRequest(count=1, question_types=(QuestionType.FILL_IN_THE_BLANK,))
    _, job = await _job(request)
    evidence = _evidence(job)
    draft = _draft(
        QuestionType.FILL_IN_THE_BLANK,
        PracticeLanguage.ZH,
        str(evidence.chunks[0].chunk_id),
    )
    with pytest.raises(InvalidGeneration, match="unreadable_cloze_context"):
        validate_draft(draft.model_copy(update={"prompt": prompt}), request, evidence)


@pytest.mark.asyncio
async def test_unobserved_picture_claim_is_rejected() -> None:
    request = GeneratePracticeRequest(count=1)
    _, job = await _job(request)
    evidence = _evidence(job)
    draft = _draft(QuestionType.TRUE_FALSE, PracticeLanguage.ZH, str(evidence.chunks[0].chunk_id))
    with pytest.raises(InvalidGeneration, match="unsupported_visual_claim"):
        validate_draft(
            draft.model_copy(update={"prompt": "在图片中，蓝色的物体是一把椅子。"}),  # noqa: RUF001
            request,
            evidence,
        )
    with pytest.raises(InvalidGeneration, match="unsupported_visual_claim"):
        validate_draft(
            draft.model_copy(update={"prompt": "图片中的动物是一只猫。"}),
            request,
            evidence,
        )


@pytest.mark.asyncio
async def test_all_items_question_requires_each_answer_term_in_evidence() -> None:
    request = GeneratePracticeRequest(count=1)
    _, job = await _job(request)
    evidence = _evidence(job)
    draft = _draft(QuestionType.SHORT_ANSWER, PracticeLanguage.ZH, str(evidence.chunks[0].chunk_id))
    with pytest.raises(InvalidGeneration, match="unsupported_answer"):
        validate_draft(
            draft.model_copy(
                update={
                    "prompt": "请列出所有问候词。",
                    "exemplar_answer": "Hello and Goodbye",
                    "rubric": (RubricCriterion(description="列出 Hello, Goodbye", weight=1),),
                }
            ),
            request,
            evidence,
        )


@pytest.mark.asyncio
async def test_multiple_blanks_are_rejected_for_single_input_exercise() -> None:
    request = GeneratePracticeRequest(count=1)
    _, job = await _job(request)
    evidence = _evidence(job)
    draft = _draft(
        QuestionType.FILL_IN_THE_BLANK, PracticeLanguage.ZH, str(evidence.chunks[0].chunk_id)
    )
    with pytest.raises(InvalidGeneration, match="multiple_blank_placeholders"):
        validate_draft(
            draft.model_copy(update={"prompt": "填写 ____ 和 ____。"}), request, evidence
        )


@pytest.mark.asyncio
async def test_repeated_dialogue_question_requires_specific_turn() -> None:
    request = GeneratePracticeRequest(count=1)
    _, job = await _job(request)
    evidence = _evidence(job)
    evidence = evidence.model_copy(
        update={
            "chunks": (
                evidence.chunks[0].model_copy(
                    update={
                        "text": "A: What's this? B: It's a desk. A: What's this? B: It's a chair."
                    }
                ),
            )
        }
    )
    draft = _draft(
        QuestionType.MULTIPLE_CHOICE, PracticeLanguage.ZH, str(evidence.chunks[0].chunk_id)
    )
    draft = draft.model_copy(
        update={
            "prompt": "在对话中，当A问“What's this?”时，B是如何回答的？",  # noqa: RUF001
            "options": (
                ChoiceOption(id="a", text="It's a desk."),
                ChoiceOption(id="b", text="It's a chair."),
            ),
        }
    )
    with pytest.raises(InvalidGeneration, match="ambiguous_dialogue_answer"):
        validate_draft(draft, request, evidence)
    with pytest.raises(InvalidGeneration, match="ambiguous_dialogue_answer"):
        validate_draft(
            draft.model_copy(
                update={"prompt": "当有人问“What's this?”时，哪个是标准回答？"}  # noqa: RUF001
            ),
            request,
            evidence,
        )
    with pytest.raises(InvalidGeneration, match="ambiguous_dialogue_answer"):
        validate_draft(
            draft.model_copy(
                update={"prompt": "根据对话，当A问'What's this?'时，B的回答是什么？"}  # noqa: RUF001
            ),
            request,
            evidence,
        )


@pytest.mark.asyncio
async def test_generic_point_to_question_with_two_correct_options_is_rejected() -> None:
    request = GeneratePracticeRequest(count=1)
    _, job = await _job(request)
    evidence = _evidence(job)
    evidence = evidence.model_copy(
        update={
            "chunks": (
                evidence.chunks[0].model_copy(update={"text": 'Point to "hello"! Point to "hi"!'}),
            )
        }
    )
    draft = _draft(
        QuestionType.MULTIPLE_CHOICE, PracticeLanguage.ZH, str(evidence.chunks[0].chunk_id)
    )
    draft = draft.model_copy(update={"prompt": "老师要求学生指向哪个单词？"})  # noqa: RUF001
    draft = draft.model_copy(
        update={"options": (ChoiceOption(id="a", text="hello"), ChoiceOption(id="b", text="hi"))}
    )
    with pytest.raises(InvalidGeneration, match="ambiguous_options"):
        validate_draft(draft, request, evidence)


@pytest.mark.asyncio
async def test_quoted_fill_phrase_must_be_contiguous_in_cited_text() -> None:
    request = GeneratePracticeRequest(count=1)
    _, job = await _job(request)
    evidence = _evidence(job)
    evidence = evidence.model_copy(
        update={
            "chunks": (
                evidence.chunks[0].model_copy(
                    update={"text": "Point to your foot. Oh no! It's on my Listen and say."}
                ),
            )
        }
    )
    draft = _draft(
        QuestionType.FILL_IN_THE_BLANK, PracticeLanguage.ZH, str(evidence.chunks[0].chunk_id)
    )
    draft = draft.model_copy(
        update={
            "prompt": "对话中说“Oh no! It's on my ____”。",
            "acceptable_answers": ("foot",),
        }
    )
    with pytest.raises(InvalidGeneration, match="unsupported_fill_phrase"):
        validate_draft(draft, request, evidence)


@pytest.mark.asyncio
async def test_unstated_injury_scene_is_rejected() -> None:
    request = GeneratePracticeRequest(count=1)
    _, job = await _job(request)
    evidence = _evidence(job)
    evidence = evidence.model_copy(
        update={
            "chunks": (
                evidence.chunks[0].model_copy(update={"text": "Point to your foot. Oh no!"}),
            )
        }
    )
    draft = _draft(
        QuestionType.FILL_IN_THE_BLANK, PracticeLanguage.ZH, str(evidence.chunks[0].chunk_id)
    )
    draft = draft.model_copy(
        update={
            "prompt": "如果脚部出现问题，对话中提到的身体部位是____。",  # noqa: RUF001
            "acceptable_answers": ("foot",),
        }
    )
    with pytest.raises(InvalidGeneration, match="unsupported_scenario"):
        validate_draft(draft, request, evidence)


@pytest.mark.parametrize(
    "prompt",
    (
        "在课文的对话中，当有人问'Where's the pen?'时，正确的回答应该是什么？",  # noqa: RUF001
        "当别人问你位置时，正确的回答是什么",  # noqa: RUF001
        "What is the correct answer to 'Where is the pen?'",
        "根据教材内容，当你向别人介绍父亲时，可能会说：",  # noqa: RUF001
        "根据教材内容，当你向别人介绍父亲时，可能会说",  # noqa: RUF001
        "父亲是警察，母亲是护士，还有一个男性角色是农民，一位女性角色是老师。",  # noqa: RUF001
        "这句话表明父亲是一名警察。",
    ),
)
@pytest.mark.asyncio
async def test_true_false_incomplete_stems_are_rejected(prompt: str) -> None:
    request = GeneratePracticeRequest(count=1)
    _, job = await _job(request)
    evidence = _evidence(job)
    draft = _draft(QuestionType.TRUE_FALSE, PracticeLanguage.ZH, str(evidence.chunks[0].chunk_id))
    with pytest.raises(InvalidGeneration, match="invalid_true_false_statement"):
        validate_draft(draft.model_copy(update={"prompt": prompt}), request, evidence)


@pytest.mark.parametrize(
    "prompt",
    (
        "课文中的'What's this?'用于询问物品名称。",
        "When asked 'Where is the pen?', a learner can answer with a place.",
        "Unit 1 teaches a greeting for friends.",
    ),
)
def test_true_false_quoted_questions_inside_statements_are_allowed(prompt: str) -> None:
    assert is_true_false_statement(prompt)


@pytest.mark.asyncio
async def test_fill_in_the_blank_requires_visible_placeholder() -> None:
    request = GeneratePracticeRequest(count=1)
    _, job = await _job(request)
    evidence = _evidence(job)
    draft = _draft(
        QuestionType.FILL_IN_THE_BLANK, PracticeLanguage.ZH, str(evidence.chunks[0].chunk_id)
    )
    with pytest.raises(InvalidGeneration, match="missing_blank_placeholder"):
        validate_draft(
            draft.model_copy(update={"prompt": "当有人递给你蛋糕时，对方可能会说什么?"}),  # noqa: RUF001
            request,
            evidence,
        )
    assert has_fill_in_blank_placeholder("请补全: ____!")
    assert has_fill_in_blank_placeholder("请补全: (  )!")


@pytest.mark.parametrize(
    "prompt",
    (
        "根据课文内容, 当有人询问“这是什么?”时, 回答“你好, 猫”的英文表达是什么?",
        "当有人问“这是一只狗吗?”时, 回答“再见, 猫”的英文表达是什么?",
        'When someone asks "What is this?", does the other speaker answer "Hello, cat"?',
    ),
)
def test_unverified_dialogue_pairing_is_detected(prompt: str) -> None:
    assert has_unverified_dialogue_pairing(prompt)


def test_single_quoted_dialogue_turn_is_not_rejected() -> None:
    assert not has_unverified_dialogue_pairing(
        "当有人询问“这是一只狗吗?”时, 对方若确认是狗, 可能会说什么?"
    )


@pytest.mark.parametrize(
    ("prompt", "answer"),
    (
        ("当有人询问“这是什么?”时, 应该如何回应?", "Hello, cat!"),
        ("询问物品是什么时, 对方可能会说什么?", "Yes, it is."),
        ("When asked 'Is it a cat?', what should you say?", "Goodbye, dog."),
    ),
)
def test_obvious_dialogue_answer_mismatch_is_detected(prompt: str, answer: str) -> None:
    assert has_obvious_dialogue_answer_mismatch(prompt, answer)


def test_object_dialogue_answer_can_be_valid() -> None:
    assert not has_obvious_dialogue_answer_mismatch(
        "当有人询问“这是什么?”时, 应该如何回应?", "It's a desk."
    )


def test_vocative_addressee_is_not_assumed_to_be_speaker() -> None:
    source = (
        "Good morning, Sam. How are you? Good morning, Sam. How are you? "
        "I'm fine, thank you. And how are you?"
    )
    prompt = "根据教材对话内容, 当Sam向对方打招呼并询问近况时, 他使用的英语表达是什么?"
    assert has_unverified_speaker_attribution(prompt, "How are you?", source)
    assert not has_unverified_speaker_attribution(
        "别人向Sam询问近况时使用了什么英语表达?", "How are you?", source
    )
    assert not has_unverified_speaker_attribution(
        "当老师对Lingling说话时, 使用了什么指令?",
        "Please stand up, Lingling.",
        "Please stand up, Lingling.",
    )


def test_self_introduction_needs_a_complete_expression() -> None:
    prompt = "在对话中, Sam 介绍自己时使用了哪个表达?"
    assert has_incomplete_self_introduction(prompt, "I'm")
    assert not has_incomplete_self_introduction(prompt, "I'm Sam")
    assert not has_incomplete_self_introduction("介绍自己时使用了哪个缩写形式?", "I'm")


def test_quantity_confirmation_is_not_an_open_count_question() -> None:
    assert has_misclassified_quantity_confirmation(
        "询问特定群体数量时可以使用'Nine girls?'这样的表达。"
    )
    assert not has_misclassified_quantity_confirmation(
        "核实已数出的女生人数时, 可以说'Nine girls?'。"
    )


def test_chant_repetition_does_not_prove_vocabulary_distinction() -> None:
    claim = "Pen and pencil是教材中通过重复练习来区分钢笔和铅笔的表达。"
    assert has_unsupported_distinction_claim(
        claim, "Pen and pencil. Pen and pencil. Pencil and pen. Say it again!"
    )
    assert not has_unsupported_distinction_claim(
        claim, "Pen and pencil are different writing tools."
    )


def test_object_mentioned_in_textbook_is_source_presence_trivia() -> None:
    assert is_metadata_question("课文中提到的物品包括desk。")
    assert is_metadata_question(
        "在课本第22页的Listen, point and say活动中, 学生需要指向的教室物品包括desk。"
    )
    assert not is_metadata_question("'Point to the desk.'是指向课桌的指令。")
    assert is_metadata_question(
        "根据教材内容, 当老师要求学生指向单词时, 以下哪一组单词是教材中明确要求学生指向的?"
    )


def test_later_named_speaker_cannot_be_credited_with_earlier_scene() -> None:
    source = (
        "Your name, please? Sam! Your name, please? Amy! Listen and say. "
        "Good afternoon. I'm Mr Li. Good afternoon, Mr Li. "
        "What's your name? I'm Sam."
    )
    prompt = "当Mr Li询问Sam的名字时, 他使用了哪句礼貌的询问语?"
    assert has_unverified_speaker_attribution(prompt, "Your name, please?", source)
    assert not has_unverified_speaker_attribution(prompt, "What's your name?", source)


def test_named_reply_must_match_next_printed_turn() -> None:
    source = (
        "Hello! Look, I'm nine. How old are you, Daming? I'm nine too. "
        "Look, I'm nine. Nine? You're six."
    )
    prompt = "当有人问'Daming, how old are you?'时, Daming是如何回答的?"
    assert has_mismatched_named_reply(prompt, "I'm nine.", source)
    assert not has_mismatched_named_reply(prompt, "I'm nine too.", source)


def test_physical_pdf_page_and_unseen_pointing_are_not_question_context() -> None:
    assert has_unverified_page_reference("在课本第55页的对话中, 父亲如何介绍?")
    assert not has_unverified_page_reference("这本教材如何介绍父亲?")
    assert has_unverified_pointing_scene("当有人指着某个物品询问时, 怎么说?")
    assert has_unverified_pointing_scene("当说话者指向自己的头部时, 他怎么说?")
    assert not has_unverified_pointing_scene("'Point to the desk'用于指示指向课桌。")


def test_family_coreference_requires_antecedent_in_same_citation() -> None:
    prompt = "这句话中的代词He指代的是说话人的父亲。"
    assert has_unverified_family_coreference(prompt, "He's a doctor. She's a driver.")
    assert not has_unverified_family_coreference(prompt, "This is my father. He's a policeman.")


@pytest.mark.asyncio
async def test_english_textbook_true_false_requires_language_target() -> None:
    request = GeneratePracticeRequest(count=1, question_types=(QuestionType.TRUE_FALSE,))
    _, job = await _job(request)
    evidence = _evidence(job)
    chunk = evidence.chunks[0].model_copy(
        update={
            "relative_path": "小学/英语/book.pdf",
            "text": "Ten fingers on my hands.",
        }
    )
    evidence = evidence.model_copy(update={"chunks": (chunk,)})
    draft = _draft(QuestionType.TRUE_FALSE, PracticeLanguage.ZH, str(chunk.chunk_id))
    with pytest.raises(InvalidGeneration, match="non_learning_question"):
        validate_draft(draft.model_copy(update={"prompt": "双手共有十个手指。"}), request, evidence)


@pytest.mark.asyncio
async def test_object_presence_trivia_is_rejected_before_storage() -> None:
    request = GeneratePracticeRequest(count=1)
    _, job = await _job(request)
    evidence = _evidence(job)
    draft = _draft(QuestionType.TRUE_FALSE, PracticeLanguage.ZH, str(evidence.chunks[0].chunk_id))
    with pytest.raises(InvalidGeneration, match="non_learning_question"):
        validate_draft(
            draft.model_copy(update={"prompt": "课文中提到的物品包括desk。"}),
            request,
            evidence,
        )


@pytest.mark.asyncio
async def test_incomplete_self_introduction_is_rejected_before_storage() -> None:
    request = GeneratePracticeRequest(count=1)
    _, job = await _job(request)
    evidence = _evidence(job)
    chunk = evidence.chunks[0]
    evidence = evidence.model_copy(
        update={"chunks": (chunk.model_copy(update={"text": "Hello, I'm Sam!"}),)}
    )
    draft = MultipleChoiceExerciseDraft(
        prompt="在对话中, Sam 介绍自己时使用了哪个表达?",
        options=(ChoiceOption(id="a", text="I'm"), ChoiceOption(id="b", text="Goodbye")),
        correct_option_id="a",
        difficulty=PracticeDifficulty.STANDARD,
        language=PracticeLanguage.ZH,
        evidence_citation_ids=(str(chunk.chunk_id),),
        rationale="The source says Hello, I'm Sam!",
    )
    with pytest.raises(InvalidGeneration, match="incomplete_expression"):
        validate_draft(draft, request, evidence)


@pytest.mark.asyncio
async def test_quantity_confirmation_mismatch_is_rejected_before_storage() -> None:
    request = GeneratePracticeRequest(count=1)
    _, job = await _job(request)
    evidence = _evidence(job)
    draft = _draft(QuestionType.TRUE_FALSE, PracticeLanguage.ZH, str(evidence.chunks[0].chunk_id))
    with pytest.raises(InvalidGeneration, match="quantity_confirmation_mismatch"):
        validate_draft(
            draft.model_copy(
                update={"prompt": "询问特定群体数量时可以使用'Nine girls?'这样的表达。"}
            ),
            request,
            evidence,
        )


@pytest.mark.asyncio
async def test_unsupported_chant_distinction_is_rejected_before_storage() -> None:
    request = GeneratePracticeRequest(count=1)
    _, job = await _job(request)
    evidence = _evidence(job)
    chunk = evidence.chunks[0]
    evidence = evidence.model_copy(
        update={
            "chunks": (
                chunk.model_copy(update={"text": "Pen and pencil. Pencil and pen. Say it again!"}),
            )
        }
    )
    draft = _draft(QuestionType.TRUE_FALSE, PracticeLanguage.ZH, str(chunk.chunk_id))
    with pytest.raises(InvalidGeneration, match="unsupported_distinction_claim"):
        validate_draft(
            draft.model_copy(
                update={"prompt": "Pen and pencil是教材中通过重复练习来区分钢笔和铅笔的表达。"}
            ),
            request,
            evidence,
        )


@pytest.mark.asyncio
async def test_unsupported_speaker_attribution_is_rejected_before_storage() -> None:
    request = GeneratePracticeRequest(count=1)
    _, job = await _job(request)
    evidence = _evidence(job)
    chunk = evidence.chunks[0]
    evidence = evidence.model_copy(
        update={
            "chunks": (
                chunk.model_copy(
                    update={"text": "Good morning, Sam. How are you? I'm fine, thank you."}
                ),
            )
        }
    )
    draft = ShortAnswerExerciseDraft(
        prompt="当Sam向对方打招呼并询问近况时, 他使用的英语表达是什么?",
        exemplar_answer="How are you?",
        rubric=(RubricCriterion(description="写出 How are you?", weight=1),),
        difficulty=PracticeDifficulty.STANDARD,
        language=PracticeLanguage.ZH,
        evidence_citation_ids=(str(chunk.chunk_id),),
        rationale="The source says How are you?",
    )
    with pytest.raises(InvalidGeneration, match="unsupported_speaker_attribution"):
        validate_draft(draft, request, evidence)


@pytest.mark.asyncio
async def test_mismatched_dialogue_answer_is_rejected_before_storage() -> None:
    request = GeneratePracticeRequest(count=1)
    _, job = await _job(request)
    evidence = _evidence(job)
    draft = _draft(
        QuestionType.MULTIPLE_CHOICE, PracticeLanguage.ZH, str(evidence.chunks[0].chunk_id)
    )
    with pytest.raises(InvalidGeneration, match="dialogue_answer_mismatch"):
        validate_draft(
            draft.model_copy(update={"prompt": "当有人询问“这是什么?”时, 应该如何回应?"}),
            request,
            evidence,
        )


@pytest.mark.asyncio
async def test_dialogue_pairing_is_rejected_before_storage() -> None:
    request = GeneratePracticeRequest(count=1)
    _, job = await _job(request)
    evidence = _evidence(job)
    draft = _draft(
        QuestionType.MULTIPLE_CHOICE, PracticeLanguage.ZH, str(evidence.chunks[0].chunk_id)
    )
    with pytest.raises(InvalidGeneration, match="unsupported_dialogue_pairing"):
        validate_draft(
            draft.model_copy(
                update={"prompt": "当有人询问“这是什么?”时, 回答“你好, 猫”的英文表达是什么?"}
            ),
            request,
            evidence,
        )


@pytest.mark.asyncio
@pytest.mark.parametrize(
    "bad_prompt",
    ("Unit 1的问候语是什么?", "根据教材内容，当你介绍父亲时，可能会说："),  # noqa: RUF001
)
async def test_worker_retries_incomplete_true_false_as_statement(bad_prompt: str) -> None:
    request = GeneratePracticeRequest(count=1, question_types=(QuestionType.TRUE_FALSE,))
    repository, job = await _job(request)
    evidence = _evidence(job)
    citation = str(evidence.chunks[0].chunk_id)
    statement = _draft(QuestionType.TRUE_FALSE, PracticeLanguage.ZH, citation)
    question = statement.model_copy(update={"prompt": bad_prompt})
    inference = InferenceStub(
        [
            GeneratedBatch(exercises=(question,)).model_dump_json(),
            GeneratedBatch(exercises=(statement,)).model_dump_json(),
        ]
    )
    worker = PracticeWorker(
        repository,
        GroundedGenerationExecutor(EvidenceStub(evidence), inference),
        worker_id="fake-worker",
    )
    assert await worker.run_once()
    completed = await repository.get_generation(job.tenant_id, job.user_id, job.id)
    assert completed is not None and completed.status.value == "ready"
    assert inference.calls == 2
    assert "A true_false prompt must be a declarative claim" in inference.messages[1][0]["content"]


@pytest.mark.asyncio
@pytest.mark.parametrize("kind", list(QuestionType))
@pytest.mark.parametrize("language", list(PracticeLanguage))
async def test_all_question_types_and_languages_generate_from_verified_evidence(
    kind: QuestionType, language: PracticeLanguage
) -> None:
    request = GeneratePracticeRequest(count=1, question_types=(kind,), language=language)
    repository, job = await _job(request)
    evidence = _evidence(job)
    draft = _draft(kind, language, str(evidence.chunks[0].chunk_id))
    inference = InferenceStub([GeneratedBatch(exercises=(draft,)).model_dump_json()])
    executor = GroundedGenerationExecutor(EvidenceStub(evidence), inference)
    worker = PracticeWorker(repository, executor, worker_id="fake-worker")
    assert await worker.run_once()
    completed = await repository.get_generation(job.tenant_id, job.user_id, job.id)
    assert completed is not None and completed.status.value == "ready"
    assert completed.practice_set_id is not None
    safe_set = await repository.get_practice_set(
        job.tenant_id, job.user_id, completed.practice_set_id
    )
    assert safe_set is not None and len(safe_set.exercises) == 1
    assert "rationale" not in safe_set.exercises[0].model_dump_json()
    assert len(inference.messages) == 1
    assert f"language={language.value}" in inference.messages[0][1]["content"]


@pytest.mark.asyncio
async def test_invalid_generation_exhausts_bounded_repairs_without_leaking_text() -> None:
    repository, job = await _job(GeneratePracticeRequest(count=1))
    evidence = _evidence(job)
    unsupported_draft = _draft(
        QuestionType.MULTIPLE_CHOICE, PracticeLanguage.ZH, str(evidence.chunks[0].chunk_id)
    )
    unsupported = unsupported_draft.model_copy(
        update={
            "options": (
                ChoiceOption(id="a", text="Bonjour"),
                ChoiceOption(id="b", text="Goodbye"),
            )
        }
    )
    raw = GeneratedBatch(exercises=(unsupported,)).model_dump_json()
    inference = InferenceStub([raw] * 6)
    worker = PracticeWorker(
        repository,
        GroundedGenerationExecutor(EvidenceStub(evidence), inference),
        worker_id="fake-worker",
    )
    assert await worker.run_once()
    failed = await repository.get_generation(job.tenant_id, job.user_id, job.id)
    assert failed is not None and failed.status.value == "failed"
    assert failed.error_code == "validation_failed"
    assert inference.calls == 6
    assert inference.temperatures == [0.1, 0.3, 0.3, 0.3, 0.3, 0.3]
    assert "Correct these earlier validation failures" in inference.messages[1][0]["content"]
    assert "Copy a short contiguous substring byte-for-byte" in inference.messages[1][0]["content"]
    assert not repository.sets
    assert "Hello is a greeting" not in str(failed.error_code)


@pytest.mark.asyncio
async def test_single_question_retry_rotates_to_other_supported_evidence() -> None:
    repository, job = await _job(GeneratePracticeRequest(count=1))
    original = _evidence(job)
    first = original.chunks[0].model_copy(
        update={"chunk_id": uuid4(), "text": "A source about another lesson.", "score": 0.99}
    )
    second = original.chunks[0]
    evidence = original.model_copy(update={"chunks": (first, second)})
    valid = _draft(QuestionType.MULTIPLE_CHOICE, PracticeLanguage.ZH, str(second.chunk_id))
    unsupported = valid.model_copy(
        update={
            "options": (ChoiceOption(id="a", text="Bonjour"), ChoiceOption(id="b", text="Goodbye"))
        }
    )
    inference = InferenceStub(
        [
            GeneratedBatch(exercises=(unsupported,)).model_dump_json(),
            GeneratedBatch(exercises=(unsupported,)).model_dump_json(),
            GeneratedBatch(exercises=(valid,)).model_dump_json(),
        ]
    )
    worker = PracticeWorker(
        repository,
        GroundedGenerationExecutor(EvidenceStub(evidence), inference),
        worker_id="fake-worker",
    )
    assert await worker.run_once()
    completed = await repository.get_generation(job.tenant_id, job.user_id, job.id)
    assert completed is not None and completed.status.value == "ready"
    assert inference.calls == 3
    assert str(first.chunk_id) in inference.messages[1][1]["content"]
    assert str(second.chunk_id) not in inference.messages[1][1]["content"]
    assert str(second.chunk_id) in inference.messages[2][1]["content"]


@pytest.mark.asyncio
async def test_partial_batch_keeps_valid_questions_and_tops_up_missing_count() -> None:
    repository, job = await _job(GeneratePracticeRequest(count=5))
    evidence = _evidence(job)
    citation = str(evidence.chunks[0].chunk_id)
    multiple_choice = _draft(QuestionType.MULTIPLE_CHOICE, PracticeLanguage.ZH, citation)
    true_false = _draft(QuestionType.TRUE_FALSE, PracticeLanguage.ZH, citation)
    fill_blank = _draft(QuestionType.FILL_IN_THE_BLANK, PracticeLanguage.ZH, citation)
    leaked = multiple_choice.model_copy(update={"prompt": "Is Hello the greeting?"})
    first = GeneratedBatch(
        exercises=(multiple_choice, true_false, fill_blank, multiple_choice, leaked)
    ).model_dump_json()
    second = GeneratedBatch(
        exercises=(true_false.model_copy(update={"prompt": "Children greet a friend in Unit 1."}),)
    ).model_dump_json()
    third = GeneratedBatch(
        exercises=(
            true_false.model_copy(update={"prompt": "A friend hears a greeting in Unit 1."}),
        )
    ).model_dump_json()
    inference = InferenceStub([first, second, third])
    worker = PracticeWorker(
        repository,
        GroundedGenerationExecutor(EvidenceStub(evidence), inference),
        worker_id="fake-worker",
    )
    assert await worker.run_once()
    completed = await repository.get_generation(job.tenant_id, job.user_id, job.id)
    assert completed is not None and completed.status.value == "ready"
    assert inference.calls == 3
    assert inference.seeds[0] != inference.seeds[1]
    assert inference.temperatures == [0.1, 0.75, 0.75]
    assert "Generate exactly 1 question" in inference.messages[1][1]["content"]
    assert multiple_choice.prompt in inference.messages[1][1]["content"]
    safe_set = await repository.get_practice_set(
        job.tenant_id, job.user_id, completed.practice_set_id
    )
    assert safe_set is not None and len(safe_set.exercises) == 5
    assert len({exercise.prompt for exercise in safe_set.exercises}) == 5
    assert all(exercise.evidence_citation_ids == (citation,) for exercise in safe_set.exercises)


@pytest.mark.asyncio
async def test_large_deficit_is_repaired_with_a_batch() -> None:
    repository, job = await _job(GeneratePracticeRequest(count=6))
    evidence = _evidence(job)
    citation = str(evidence.chunks[0].chunk_id)
    base = _draft(QuestionType.TRUE_FALSE, PracticeLanguage.ZH, citation)
    first = GeneratedBatch(exercises=(base,)).model_dump_json()
    top_up = GeneratedBatch(
        exercises=tuple(
            base.model_copy(update={"prompt": f"A friend hears greeting {index} in Unit 1."})
            for index in range(4)
        )
    ).model_dump_json()
    final = GeneratedBatch(
        exercises=(base.model_copy(update={"prompt": "A friend hears a greeting in Unit 1."}),)
    ).model_dump_json()
    inference = InferenceStub([first, top_up, final])
    worker = PracticeWorker(
        repository,
        GroundedGenerationExecutor(EvidenceStub(evidence), inference),
        worker_id="fake-worker",
    )
    assert await worker.run_once()
    completed = await repository.get_generation(job.tenant_id, job.user_id, job.id)
    assert completed is not None and completed.status.value == "ready"
    assert inference.calls == 3
    assert "Generate exactly 4 questions" in inference.messages[1][1]["content"]


@pytest.mark.asyncio
async def test_one_malformed_draft_does_not_discard_valid_batch_members() -> None:
    repository, job = await _job(GeneratePracticeRequest(count=3))
    evidence = _evidence(job)
    citation = str(evidence.chunks[0].chunk_id)
    base = _draft(QuestionType.TRUE_FALSE, PracticeLanguage.ZH, citation)
    second = base.model_copy(update={"prompt": "Children greet a friend in Unit 1."})
    third = base.model_copy(update={"prompt": "A friend hears a greeting in Unit 1."})
    first_payload = {
        "exercises": [
            base.model_dump(mode="json"),
            {"type": "true_false"},
            second.model_dump(mode="json"),
        ]
    }
    inference = InferenceStub(
        [
            json.dumps(first_payload),
            GeneratedBatch(exercises=(third,)).model_dump_json(),
        ]
    )
    worker = PracticeWorker(
        repository,
        GroundedGenerationExecutor(EvidenceStub(evidence), inference),
        worker_id="fake-worker",
    )
    assert await worker.run_once()
    completed = await repository.get_generation(job.tenant_id, job.user_id, job.id)
    assert completed is not None and completed.status.value == "ready"
    assert inference.calls == 2
    assert "Generate exactly 1 question" in inference.messages[1][1]["content"]


@pytest.mark.asyncio
async def test_whole_batch_schema_failure_retries_full_batch_once() -> None:
    repository, job = await _job(GeneratePracticeRequest(count=4))
    evidence = _evidence(job)
    citation = str(evidence.chunks[0].chunk_id)
    base = _draft(QuestionType.TRUE_FALSE, PracticeLanguage.ZH, citation)
    valid = GeneratedBatch(
        exercises=tuple(
            base.model_copy(update={"prompt": f"A friend hears greeting {index} in Unit 1."})
            for index in range(4)
        )
    ).model_dump_json()
    inference = InferenceStub(["not json", valid])
    worker = PracticeWorker(
        repository,
        GroundedGenerationExecutor(EvidenceStub(evidence), inference),
        worker_id="fake-worker",
    )
    assert await worker.run_once()
    completed = await repository.get_generation(job.tenant_id, job.user_id, job.id)
    assert completed is not None and completed.status.value == "ready"
    assert inference.calls == 2
    assert "Generate exactly 4 questions" in inference.messages[1][1]["content"]


@pytest.mark.asyncio
async def test_large_set_has_longer_bounded_deadline() -> None:
    _, small_job = await _job(GeneratePracticeRequest(count=5))
    _, large_job = await _job(GeneratePracticeRequest(count=20))
    assert small_job.deadline_at - small_job.created_at == timedelta(minutes=5)
    assert large_job.deadline_at - large_job.created_at == timedelta(minutes=8)


@pytest.mark.asyncio
async def test_count_mismatch_tops_up_instead_of_discarding_valid_questions() -> None:
    repository, job = await _job(GeneratePracticeRequest(count=3))
    evidence = _evidence(job)
    citation = str(evidence.chunks[0].chunk_id)
    first_draft = _draft(QuestionType.TRUE_FALSE, PracticeLanguage.ZH, citation)
    second_draft = first_draft.model_copy(update={"prompt": "Children greet a friend in Unit 1."})
    third_draft = first_draft.model_copy(update={"prompt": "A friend hears a greeting in Unit 1."})
    inference = InferenceStub(
        [
            GeneratedBatch(exercises=(first_draft, second_draft)).model_dump_json(),
            GeneratedBatch(exercises=(third_draft,)).model_dump_json(),
        ]
    )
    worker = PracticeWorker(
        repository,
        GroundedGenerationExecutor(EvidenceStub(evidence), inference),
        worker_id="fake-worker",
    )
    assert await worker.run_once()
    completed = await repository.get_generation(job.tenant_id, job.user_id, job.id)
    assert completed is not None and completed.status.value == "ready"
    assert "Generate exactly 1 question" in inference.messages[1][1]["content"]


@pytest.mark.asyncio
async def test_repair_focuses_on_underused_evidence_and_a_single_type() -> None:
    repository, job = await _job(GeneratePracticeRequest(count=2))
    original = _evidence(job)
    second_chunk = original.chunks[0].model_copy(
        update={
            "chunk_id": uuid4(),
            "text": "Goodbye is a farewell. Children say Goodbye when they leave a friend.",
            "anchor_value": "5",
        }
    )
    evidence = original.model_copy(update={"chunks": (*original.chunks, second_chunk)})
    first_draft = _draft(
        QuestionType.TRUE_FALSE, PracticeLanguage.ZH, str(original.chunks[0].chunk_id)
    )
    second_draft = first_draft.model_copy(
        update={
            "prompt": "Children say Goodbye when they leave a friend.",
            "evidence_citation_ids": (str(second_chunk.chunk_id),),
            "rationale": "The cited text says Goodbye is a farewell.",
        }
    )
    inference = InferenceStub(
        [
            GeneratedBatch(exercises=(first_draft,)).model_dump_json(),
            GeneratedBatch(exercises=(second_draft,)).model_dump_json(),
        ]
    )
    worker = PracticeWorker(
        repository,
        GroundedGenerationExecutor(EvidenceStub(evidence), inference),
        worker_id="fake-worker",
    )
    assert await worker.run_once()
    completed = await repository.get_generation(job.tenant_id, job.user_id, job.id)
    assert completed is not None and completed.status.value == "ready"
    repair_prompt = inference.messages[1][1]["content"]
    assert str(second_chunk.chunk_id) in repair_prompt
    assert str(original.chunks[0].chunk_id) not in repair_prompt
    assert "allowed types=multiple_choice" in repair_prompt
    assert "This is a repair call" in inference.messages[1][0]["content"]


@pytest.mark.asyncio
async def test_grounding_repair_uses_only_supplied_matching_excerpt() -> None:
    _, job = await _job(GeneratePracticeRequest(count=1))
    original = _evidence(job)
    other = original.chunks[0].model_copy(
        update={
            "chunk_id": uuid4(),
            "text": "Goodbye is a farewell when friends leave.",
        }
    )
    evidence = original.model_copy(update={"chunks": (*original.chunks, other)})
    draft = _draft(
        QuestionType.MULTIPLE_CHOICE,
        PracticeLanguage.ZH,
        str(original.chunks[0].chunk_id),
    ).model_copy(
        update={
            "prompt": "Which word is used when friends leave?",
            "correct_option_id": "b",
        }
    )
    with pytest.raises(InvalidGeneration, match="unsupported_answer"):
        validate_draft(draft, GeneratePracticeRequest(count=1), evidence)
    repaired = repair_grounding(draft, evidence)
    assert repaired.evidence_citation_ids == (str(other.chunk_id),)
    validate_draft(repaired, GeneratePracticeRequest(count=1), evidence)
    invalid_id = draft.model_copy(update={"evidence_citation_ids": (str(uuid4()),)})
    repaired_invalid_id = repair_grounding(invalid_id, evidence)
    assert repaired_invalid_id.evidence_citation_ids == (str(other.chunk_id),)
    validate_draft(repaired_invalid_id, GeneratePracticeRequest(count=1), evidence)
    assert repair_grounding(draft, original) == draft


@pytest.mark.asyncio
async def test_rubric_weights_are_normalized_without_changing_answer() -> None:
    _, job = await _job(GeneratePracticeRequest(count=1))
    evidence = _evidence(job)
    draft = _draft(
        QuestionType.SHORT_ANSWER,
        PracticeLanguage.ZH,
        str(evidence.chunks[0].chunk_id),
    ).model_copy(
        update={
            "rubric": (
                RubricCriterion(description="Greeting", weight=1),
                RubricCriterion(description="Context", weight=1),
            ),
        }
    )
    repaired = repair_grounding(draft, evidence)
    assert [item.weight for item in repaired.rubric] == [0.5, 0.5]
    assert repaired.exemplar_answer == draft.exemplar_answer
    validate_draft(repaired, GeneratePracticeRequest(count=1), evidence)


@pytest.mark.asyncio
async def test_fifth_question_can_be_repaired_after_seven_calls() -> None:
    repository, job = await _job(GeneratePracticeRequest(count=5))
    evidence = _evidence(job)
    citation = str(evidence.chunks[0].chunk_id)
    base = _draft(QuestionType.TRUE_FALSE, PracticeLanguage.ZH, citation)
    initial = GeneratedBatch(
        exercises=tuple(
            base.model_copy(update={"prompt": f"Children greet friend {index} in Unit 1."})
            for index in range(4)
        )
    ).model_dump_json()
    bad = _draft(QuestionType.MULTIPLE_CHOICE, PracticeLanguage.ZH, citation).model_copy(
        update={
            "options": (
                ChoiceOption(id="a", text="Bonjour"),
                ChoiceOption(id="b", text="Goodbye"),
            )
        }
    )
    bad_batch = GeneratedBatch(exercises=(bad,)).model_dump_json()
    final = GeneratedBatch(
        exercises=(base.model_copy(update={"prompt": "A friend hears Hello in Unit 1."}),)
    ).model_dump_json()
    inference = InferenceStub([initial, *([bad_batch] * 6), final])
    worker = PracticeWorker(
        repository,
        GroundedGenerationExecutor(EvidenceStub(evidence), inference),
        worker_id="fake-worker",
    )
    assert await worker.run_once()
    completed = await repository.get_generation(job.tenant_id, job.user_id, job.id)
    assert completed is not None and completed.status.value == "ready"
    assert inference.calls == 8
    assert all(
        "Generate exactly 1 question" in item[1]["content"] for item in inference.messages[1:]
    )


@pytest.mark.asyncio
async def test_insufficient_evidence_never_calls_inference_or_stores_questions() -> None:
    repository, job = await _job(GeneratePracticeRequest(count=1))
    empty = _evidence(job).model_copy(update={"chunks": ()})
    inference = InferenceStub([])
    worker = PracticeWorker(
        repository,
        GroundedGenerationExecutor(EvidenceStub(empty), inference),
        worker_id="fake-worker",
    )
    assert await worker.run_once()
    failed = await repository.get_generation(job.tenant_id, job.user_id, job.id)
    assert failed is not None and failed.error_code == "insufficient_evidence"
    assert inference.calls == 0 and not repository.sets


def test_delegation_is_bound_to_job_and_expires() -> None:
    principal = _principal()
    secret = Settings().practice_delegation_secret.get_secret_value()
    token = issue_practice_delegation(
        principal,
        generation_id=uuid4(),
        book_id=uuid4(),
        course_id=uuid4(),
        content_version_id=uuid4(),
        expires_at=datetime.now(UTC) + timedelta(minutes=5),
        secret=secret,
    )
    assert verify_practice_delegation(token, secret).tenant_id == principal.tenant_id
    with pytest.raises(jwt.PyJWTError):
        verify_practice_delegation(token, "a-different-long-enough-delegation-secret")
    expired = issue_practice_delegation(
        principal,
        generation_id=uuid4(),
        book_id=uuid4(),
        course_id=uuid4(),
        content_version_id=uuid4(),
        expires_at=datetime.now(UTC) - timedelta(seconds=1),
        secret=secret,
    )
    with pytest.raises(jwt.PyJWTError):
        verify_practice_delegation(expired, secret)


def test_strict_schema_rejects_extra_answer_fields() -> None:
    payload = json.loads(
        GeneratedBatch(
            exercises=(_draft(QuestionType.TRUE_FALSE, PracticeLanguage.ZH, str(uuid4())),)
        ).model_dump_json()
    )
    payload["exercises"][0]["invented_answer"] = "should not pass"
    with pytest.raises(ValidationError):
        GeneratedBatch.model_validate(payload)


@pytest.mark.asyncio
async def test_lm_studio_json_schema_and_reasoning_content_fallback() -> None:
    observed: dict[str, object] = {}

    def respond(request: httpx.Request) -> httpx.Response:
        observed.update(json.loads(request.content))
        observed["correlation_id"] = request.headers.get("X-Correlation-ID")
        return httpx.Response(
            200,
            json={
                "choices": [{"message": {"content": "", "reasoning_content": '{"exercises": []}'}}]
            },
        )

    async with httpx.AsyncClient(
        transport=httpx.MockTransport(respond), base_url="http://lm.test/v1"
    ) as http:
        inference = OpenAICompatiblePracticeInference(
            "http://lm.test/v1", "fake-model", "fake-key", http
        )
        assert await inference.generate_json(
            [{"role": "user", "content": "test"}], 42, "corr", count=1
        ) == ('{"exercises": []}')
    assert observed["seed"] == 42
    assert observed["temperature"] == 0.1
    assert observed["correlation_id"] == "corr"
    response_format = observed["response_format"]
    assert isinstance(response_format, dict)
    assert response_format["type"] == "json_schema"
    assert response_format["json_schema"]["schema"]["type"] == "object"
    exercises_schema = response_format["json_schema"]["schema"]["properties"]["exercises"]
    assert exercises_schema["minItems"] == exercises_schema["maxItems"] == 1


@pytest.mark.asyncio
async def test_lm_studio_empty_api_key_omits_authorization_header() -> None:
    inference = OpenAICompatiblePracticeInference("http://lm.test/v1", "fake-model", "")
    try:
        assert "Authorization" not in inference._client.headers
    finally:
        await inference.aclose()

    authenticated = OpenAICompatiblePracticeInference("http://lm.test/v1", "fake-model", "fake-key")
    try:
        assert authenticated._client.headers["Authorization"] == "Bearer fake-key"
    finally:
        await authenticated.aclose()
