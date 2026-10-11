"""Agent evidence -> structured model -> deterministic validation."""

from __future__ import annotations

from datetime import UTC, datetime
from typing import Protocol

import structlog
from pydantic import ValidationError

from course_tutor_contracts import (
    ExerciseDraft,
    GeneratePracticeRequest,
    PracticeEvidenceRequest,
    PracticeEvidenceResponse,
    QuestionType,
)
from course_tutor_practice.application.validation import (
    InvalidGeneration,
    question_fingerprint,
    validate_batch,
    validate_draft,
)
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

logger = structlog.get_logger(__name__)


class EvidenceProvider(Protocol):
    async def retrieve(
        self, request: PracticeEvidenceRequest, delegation_token: str, correlation_id: str
    ) -> PracticeEvidenceResponse: ...


class InferenceProvider(Protocol):
    model: str

    async def generate_json(
        self,
        messages: list[dict[str, str]],
        seed: int,
        correlation_id: str,
        *,
        count: int,
        temperature: float,
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
        outline_node_id = job.request_payload.get("_outline_node_id")
        if outline_node_id is not None and not isinstance(outline_node_id, str):
            raise GenerationFailure("invalid_outline_scope")
        evidence = await self._evidence.retrieve(
            PracticeEvidenceRequest(
                generation_id=job.id,
                book_id=job.book_id,
                course_id=job.course_id,
                content_version_id=job.content_version_id,
                query=query,
                outline_node_id=outline_node_id,
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
        accepted: list[ExerciseDraft] = []
        fingerprints: set[str] = set()
        # One full batch, then bounded top-ups. Single-question jobs retain one repair.
        max_calls = 2 if request.count == 1 else min(8, request.count + 2)
        for attempt in range(max_calls):
            if datetime.now(UTC) >= job.deadline_at:
                raise GenerationFailure("deadline_exceeded")
            missing = request.count - len(accepted)
            attempt_seed = (seed + attempt) % (2**31)
            prompt_evidence = context.evidence
            prompt_types = request.question_types
            if attempt and accepted:
                # Give a small local model a concrete, underused source and a
                # specific type instead of asking it to recreate the whole set.
                eligible = (
                    tuple(
                        chunk for chunk in context.evidence.chunks if len(chunk.text.strip()) >= 120
                    )
                    or context.evidence.chunks
                )
                cited = [citation for draft in accepted for citation in draft.evidence_citation_ids]
                ranked_chunks = sorted(
                    eligible,
                    key=lambda chunk: (cited.count(str(chunk.chunk_id)), -len(chunk.text)),
                )
                focus_chunk = ranked_chunks[(attempt - 1) % len(ranked_chunks)]
                prompt_evidence = context.evidence.model_copy(update={"chunks": (focus_chunk,)})
                repair_order = (
                    QuestionType.TRUE_FALSE,
                    QuestionType.FILL_IN_THE_BLANK,
                    QuestionType.MULTIPLE_CHOICE,
                    QuestionType.SHORT_ANSWER,
                )
                repair_types = tuple(
                    kind for kind in repair_order if kind in request.question_types
                )
                prompt_types = (repair_types[(attempt - 1) % len(repair_types)],)
            messages = build_messages(
                request,
                prompt_evidence,
                attempt_seed,
                count=missing,
                accepted_prompts=tuple(draft.prompt for draft in accepted),
                allowed_types=prompt_types,
            )
            content = await self._inference.generate_json(
                messages,
                attempt_seed,
                job.correlation_id,
                count=missing,
                temperature=0.1 if attempt == 0 else 0.75,
            )
            try:
                batch = GeneratedBatch.model_validate_json(content)
            except ValidationError:
                logger.warning(
                    "practice_generation_validation_rejected",
                    generation_id=str(job.id),
                    attempt=attempt + 1,
                    reason="invalid_schema",
                    requested_count=missing,
                )
                continue
            for draft in batch.exercises:
                try:
                    validate_draft(draft, request, context.evidence)
                    fingerprint = question_fingerprint(draft.prompt)
                    if fingerprint in fingerprints:
                        raise InvalidGeneration("duplicate_question")
                except InvalidGeneration as exc:
                    logger.warning(
                        "practice_generation_validation_rejected",
                        generation_id=str(job.id),
                        attempt=attempt + 1,
                        reason=exc.code,
                    )
                    continue
                accepted.append(draft)
                fingerprints.add(fingerprint)
                if len(accepted) == request.count:
                    break
            if len(accepted) != request.count:
                logger.info(
                    "practice_generation_top_up",
                    generation_id=str(job.id),
                    attempt=attempt + 1,
                    accepted_count=len(accepted),
                    missing_count=request.count - len(accepted),
                )
                continue
            complete_batch = GeneratedBatch(exercises=tuple(accepted))
            validate_batch(complete_batch, request, context.evidence)
            return GenerationOutcome(
                drafts=complete_batch.exercises,
                seed=seed,
                prompt_version=PROMPT_VERSION,
                model_version=self._inference.model,
                validator_version=VALIDATOR_VERSION,
                retrieval_trace_id=context.evidence.retrieval_trace_id,
            )
        raise GenerationFailure("validation_failed")
