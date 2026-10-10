"""Agent evidence -> structured model -> deterministic validation."""

from __future__ import annotations

from typing import Protocol

from pydantic import ValidationError

from course_tutor_contracts import (
    GeneratePracticeRequest,
    PracticeEvidenceRequest,
    PracticeEvidenceResponse,
)
from course_tutor_practice.application.validation import InvalidGeneration, validate_batch
from course_tutor_practice.domain import GenerationRecord
from course_tutor_practice.generation.errors import GenerationFailure
from course_tutor_practice.generation.prompts import build_messages
from course_tutor_practice.generation.schemas import (
    PROMPT_VERSION,
    VALIDATOR_VERSION,
    GeneratedBatch,
    GenerationContext,
    GenerationOutcome,
)


class EvidenceProvider(Protocol):
    async def retrieve(
        self, request: PracticeEvidenceRequest, delegation_token: str, correlation_id: str
    ) -> PracticeEvidenceResponse: ...


class InferenceProvider(Protocol):
    model: str

    async def generate_json(
        self, messages: list[dict[str, str]], seed: int, correlation_id: str
    ) -> str: ...


class GroundedGenerationExecutor:
    def __init__(self, evidence: EvidenceProvider, inference: InferenceProvider) -> None:
        self._evidence = evidence
        self._inference = inference

    @staticmethod
    def _request(job: GenerationRecord) -> GeneratePracticeRequest:
        return GeneratePracticeRequest.model_validate(
            {key: value for key, value in job.request_payload.items() if not key.startswith("_")}
        )

    async def retrieve(self, job: GenerationRecord) -> GenerationContext:
        token = job.request_payload.get("_delegation_token")
        if not isinstance(token, str) or not token:
            raise GenerationFailure("delegation_unavailable")
        request = self._request(job)
        topic = job.request_payload.get("_module_title") or request.topic
        query = str(topic or "textbook core concepts vocabulary dialogue examples")[:1000]
        evidence = await self._evidence.retrieve(
            PracticeEvidenceRequest(
                generation_id=job.id,
                book_id=job.book_id,
                course_id=job.course_id,
                content_version_id=job.content_version_id,
                query=query,
                limit=min(20, max(5, job.requested_count)),
            ),
            token,
            job.correlation_id,
        )
        if not evidence.chunks:
            raise GenerationFailure("insufficient_evidence")
        return GenerationContext(evidence)

    async def generate(
        self, job: GenerationRecord, context: GenerationContext
    ) -> GenerationOutcome:
        request = self._request(job)
        seed = job.id.int % (2**31)
        messages = build_messages(request, context.evidence, seed)
        for attempt in range(2):
            content = await self._inference.generate_json(messages, seed, job.correlation_id)
            try:
                batch = GeneratedBatch.model_validate_json(content)
                validate_batch(batch, request, context.evidence)
            except (ValidationError, InvalidGeneration) as exc:
                if attempt:
                    raise GenerationFailure("validation_failed") from exc
                reason = exc.code if isinstance(exc, InvalidGeneration) else "invalid_schema"
                messages = [
                    *messages,
                    {
                        "role": "user",
                        "content": (
                            "Your previous response failed validation: " + reason + ". "
                            "Try once more. Return only schema-valid JSON grounded "
                            "in the same evidence. For multiple choice and fill-in "
                            "questions, copy the protected answer verbatim from a cited "
                            "excerpt; never translate the answer text."
                        ),
                    },
                ]
                continue
            return GenerationOutcome(
                drafts=batch.exercises,
                seed=seed,
                prompt_version=PROMPT_VERSION,
                model_version=self._inference.model,
                validator_version=VALIDATOR_VERSION,
                retrieval_trace_id=context.evidence.retrieval_trace_id,
            )
        raise GenerationFailure("validation_failed")  # pragma: no cover
