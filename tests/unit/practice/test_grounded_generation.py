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

    async def retrieve(self, request, token, correlation_id):  # type: ignore[no-untyped-def]
        self.calls += 1
        claims = verify_practice_delegation(
            token, Settings().practice_delegation_secret.get_secret_value()
        )
        assert claims.generation_id == request.generation_id == self.response.generation_id
        assert claims.content_version_id == request.content_version_id
        assert correlation_id == "corr"
        return self.response


class InferenceStub:
    model = "fake-practice-model"

    def __init__(self, outputs: list[str]) -> None:
        self.outputs = outputs
        self.calls = 0
        self.messages: list[list[dict[str, str]]] = []

    async def generate_json(
        self, messages: list[dict[str, str]], seed: int, correlation_id: str
    ) -> str:
        assert seed >= 0
        assert correlation_id == "corr"
        self.messages.append(messages)
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
async def test_invalid_generation_repairs_once_then_fails_without_leaking_text() -> None:
    repository, job = await _job(GeneratePracticeRequest(count=1))
    evidence = _evidence(job)
    unsupported = _draft(QuestionType.MULTIPLE_CHOICE, PracticeLanguage.ZH, str(uuid4()))
    raw = GeneratedBatch(exercises=(unsupported,)).model_dump_json()
    inference = InferenceStub([raw, raw])
    worker = PracticeWorker(
        repository,
        GroundedGenerationExecutor(EvidenceStub(evidence), inference),
        worker_id="fake-worker",
    )
    assert await worker.run_once()
    failed = await repository.get_generation(job.tenant_id, job.user_id, job.id)
    assert failed is not None and failed.status.value == "failed"
    assert failed.error_code == "validation_failed"
    assert inference.calls == 2
    assert not repository.sets
    assert "Hello is a greeting" not in str(failed.error_code)


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
        assert await inference.generate_json([{"role": "user", "content": "test"}], 42, "corr") == (
            '{"exercises": []}'
        )
    assert observed["seed"] == 42
    assert observed["correlation_id"] == "corr"
    response_format = observed["response_format"]
    assert isinstance(response_format, dict)
    assert response_format["type"] == "json_schema"
    assert response_format["json_schema"]["schema"]["type"] == "object"
