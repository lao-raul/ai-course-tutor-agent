"""Grounded chat with bounded evidence, validated citations and real SSE streaming."""

from __future__ import annotations

import asyncio
import json
import math
import re
import time
import uuid
from collections.abc import AsyncGenerator
from dataclasses import dataclass
from typing import TYPE_CHECKING, Annotated, Any

import structlog
from course_tutor_memory import TeachingPolicy, build_teaching_directive, solution_content_allowed
from course_tutor_retrieval.scope import extract_content_scopes
from fastapi import APIRouter, Body, Depends, HTTPException, Path, status
from fastapi.responses import StreamingResponse
from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession

from course_tutor_api.auth import Principal, get_current_principal, principal_can_access_course
from course_tutor_api.db import ContentVersion, ContentVersionSource, Course, RetrievalTrace
from course_tutor_api.dependencies import (
    Dependencies,
    RedisRateLimiter,
    dependencies_from_request,
    get_session,
)
from course_tutor_api.memory_store import (
    ConversationContext,
    persist_assistant_turn,
    prepare_conversation,
    teaching_policy_for,
)
from course_tutor_contracts.enums import AccessLabel, ChunkClass, ContentVersionStatus
from course_tutor_contracts.retrieval import ChatCitation, ChatRequest, RetrievedChunk
from course_tutor_shared import observe_chat_ttft, observe_retrieval, span

if TYPE_CHECKING:
    from course_tutor_api.providers.base import ChatMessage

router = APIRouter(prefix="/v1/courses", tags=["chat"])
logger = structlog.get_logger(__name__)

MAX_EVIDENCE_CHUNKS = 5
MAX_EVIDENCE_TOKENS = 3500
MIN_RELEVANCE_SCORE = 0.2
HIGH_CONFIDENCE_RELEVANCE_SCORE = 0.5
CITATION_MARKER = "CITATIONS:"
MAX_CITATION_TRAILER_CHARS = 16_384

_RELEVANCE_TOKEN = re.compile(r"[\w*]+", re.UNICODE)
_RELEVANCE_STOPWORDS = {
    "about",
    "and",
    "are",
    "does",
    "for",
    "from",
    "how",
    "into",
    "the",
    "this",
    "what",
    "when",
    "where",
    "which",
    "who",
    "why",
    "will",
    "with",
}


@dataclass(frozen=True, slots=True)
class EvidencePack:
    candidates: tuple[RetrievedChunk, ...]
    evidence: tuple[RetrievedChunk, ...]
    citation_map: dict[int, ChatCitation]
    timings_ms: dict[str, float]


def _get_retrieval_service(deps: Dependencies) -> Any:
    from course_tutor_retrieval.search import DenseRetrievalService

    return DenseRetrievalService(qdrant_client=deps.qdrant_client, embed_provider=deps.llm)


def _get_reranker() -> Any:
    from course_tutor_retrieval.reranker import Reranker

    return Reranker()


def _estimate_tokens(text: str) -> int:
    """Conservative tokenizer-independent estimate used for hard prompt budgets."""
    return max(1, math.ceil(len(text) / 4)) if text else 0


def _relevance_terms(value: str) -> set[str]:
    return {
        token
        for token in _RELEVANCE_TOKEN.findall(value.lower())
        if len(token) >= 3 and token not in _RELEVANCE_STOPWORDS
    }


def _has_lexical_support(query: str, chunk: RetrievedChunk) -> bool:
    if set(extract_content_scopes(query)) & set(extract_content_scopes(chunk.relative_path)):
        return True
    query_terms = _relevance_terms(query)
    if not query_terms:
        return False
    evidence_terms = _relevance_terms(f"{chunk.relative_path} {chunk.text}")
    return bool(query_terms & evidence_terms)


def _bounded_evidence(candidates: list[RetrievedChunk], query: str) -> list[RetrievedChunk]:
    evidence: list[RetrievedChunk] = []
    remaining = MAX_EVIDENCE_TOKENS
    for chunk in candidates:
        if len(evidence) >= MAX_EVIDENCE_CHUNKS or chunk.score < MIN_RELEVANCE_SCORE:
            continue
        if chunk.score < HIGH_CONFIDENCE_RELEVANCE_SCORE and not _has_lexical_support(query, chunk):
            continue
        estimated = _estimate_tokens(chunk.text)
        if estimated <= remaining:
            evidence.append(chunk)
            remaining -= estimated
            continue
        if remaining >= 32:
            truncated = chunk.model_copy(update={"text": chunk.text[: remaining * 4]})
            evidence.append(truncated)
        break
    return evidence


async def _build_evidence_pack(
    retrieval_service: Any,
    reranker: Any,
    tenant_id: uuid.UUID,
    course_id: uuid.UUID,
    version_id: uuid.UUID,
    access_label: AccessLabel,
    query: str,
    source_ids: tuple[uuid.UUID, ...] | None = None,
    service_name: str = "agent-api",
) -> EvidencePack:
    retrieval_started = time.perf_counter()
    with span("rag.retrieve", **{"course_tutor.retrieval.limit": 20}):
        result = await retrieval_service.search(
            query=query,
            tenant_id=tenant_id,
            course_id=course_id,
            content_version_id=version_id,
            access_label=access_label,
            limit=20,
            source_ids=source_ids,
        )
    rerank_started = time.perf_counter()
    source_limit = MAX_EVIDENCE_CHUNKS if extract_content_scopes(query) else None
    reranked = reranker.rerank(
        result.candidates,
        max_from_same_source=source_limit,
    )
    evidence = _bounded_evidence(reranked, query)
    rerank_ms = (time.perf_counter() - rerank_started) * 1000
    observe_retrieval(
        service_name,
        "evidence" if evidence else "empty",
        time.perf_counter() - retrieval_started,
    )

    citation_map = {
        number: ChatCitation(
            chunk_id=chunk.chunk_id,
            relative_path=chunk.relative_path,
            anchor_type=chunk.anchor_type,
            anchor_value=chunk.anchor_value,
            text_excerpt=chunk.text[:200],
        )
        for number, chunk in enumerate(evidence, 1)
    }
    return EvidencePack(
        candidates=tuple(result.candidates),
        evidence=tuple(evidence),
        citation_map=citation_map,
        timings_ms={**result.timings_ms, "rerank_ms": round(rerank_ms, 2)},
    )


def _apply_teaching_policy(
    pack: EvidencePack, policy: TeachingPolicy, body: ChatRequest
) -> EvidencePack:
    evidence = pack.evidence
    if body.assessment_mode and not solution_content_allowed(policy, body.attempt_number):
        evidence = tuple(
            chunk
            for chunk in evidence
            if chunk.chunk_class not in {ChunkClass.EXERCISE_SOLUTION, ChunkClass.ASSESSMENT}
        )
    citation_map = {
        number: ChatCitation(
            chunk_id=chunk.chunk_id,
            relative_path=chunk.relative_path,
            anchor_type=chunk.anchor_type,
            anchor_value=chunk.anchor_value,
            text_excerpt=chunk.text[:200],
        )
        for number, chunk in enumerate(evidence, 1)
    }
    return EvidencePack(
        candidates=pack.candidates,
        evidence=evidence,
        citation_map=citation_map,
        timings_ms=pack.timings_ms,
    )


def _build_prompt(
    query: str,
    evidence: tuple[RetrievedChunk, ...],
    conversation: ConversationContext | None = None,
    teaching_directive: str | None = None,
) -> list[ChatMessage]:
    from course_tutor_api.providers.base import ChatMessage

    evidence_lines = [
        (
            f"[Source {number}] [chunk_id={chunk.chunk_id}] "
            f"({chunk.relative_path}, {chunk.anchor_type.value} {chunk.anchor_value}):\n"
            f"{chunk.text}"
        )
        for number, chunk in enumerate(evidence, 1)
    ]
    system_message = (
        "You are a helpful course teaching assistant. Answer only from the supplied "
        "course material and clearly abstain when it is insufficient. Cite supported "
        "claims with [Source N]. Never invent a source. Format the visible answer as "
        "GitHub-flavored Markdown, using $...$ for inline mathematics and $$...$$ for "
        "display mathematics; never emit raw HTML. After the visible answer, output "
        "a private machine-readable trailer on a new line using exactly "
        'CITATIONS:[{"source":1,"chunk_id":"UUID"}]. Include only sources actually '
        "used in the answer and preserve each supplied chunk_id exactly."
    )
    if teaching_directive:
        system_message = f"{system_message}\n\nTeaching policy:\n{teaching_directive}"
    context_parts: list[str] = []
    if conversation is not None:
        if conversation.rolling_summary:
            context_parts.append(f"Bounded session summary:\n{conversation.rolling_summary}")
        if conversation.recent_turns:
            turns = "\n".join(f"{turn.role}: {turn.content}" for turn in conversation.recent_turns)
            context_parts.append(f"Recent course conversation:\n{turns}")
        if conversation.recalled_facts:
            facts = "\n".join(
                f"- {fact.type.value}: {fact.value}" for fact in conversation.recalled_facts
            )
            context_parts.append(f"Learner-approved long-term memory:\n{facts}")
    context = f"{'\n\n'.join(context_parts)}\n\n" if context_parts else ""
    return [
        ChatMessage(role="system", content=system_message),
        ChatMessage(
            role="user",
            content=(
                f"{context}Course material:\n{'\n\n'.join(evidence_lines)}\n\nQuestion: {query}"
            ),
        ),
    ]


class CitationTrailerParser:
    """Incrementally hides a possibly split citation trailer from visible output."""

    def __init__(self) -> None:
        self._pending = ""
        self._trailer = ""
        self._found_marker = False

    @staticmethod
    def _marker_prefix_suffix_length(value: str) -> int:
        maximum = min(len(value), len(CITATION_MARKER) - 1)
        for length in range(maximum, 0, -1):
            if value.endswith(CITATION_MARKER[:length]):
                return length
        return 0

    def feed(self, value: str) -> list[str]:
        if self._found_marker:
            self._append_trailer(value)
            return []

        self._pending += value
        if CITATION_MARKER in self._pending:
            visible, trailer = self._pending.split(CITATION_MARKER, 1)
            self._pending = ""
            self._found_marker = True
            self._append_trailer(trailer)
            return [visible] if visible else []

        held = self._marker_prefix_suffix_length(self._pending)
        safe_length = len(self._pending) - held
        if safe_length == 0:
            return []
        visible = self._pending[:safe_length]
        self._pending = self._pending[safe_length:]
        return [visible]

    def finish_visible(self) -> str:
        if self._found_marker:
            return ""
        visible = self._pending
        self._pending = ""
        return visible

    def _append_trailer(self, value: str) -> None:
        self._trailer += value
        if len(self._trailer) > MAX_CITATION_TRAILER_CHARS:
            raise ValueError("citation trailer exceeds maximum size")

    def validated_citations(self, citation_map: dict[int, ChatCitation]) -> list[ChatCitation]:
        if not self._found_marker:
            return []
        try:
            raw, _remainder = json.JSONDecoder().raw_decode(self._trailer.strip())
        except (json.JSONDecodeError, TypeError):
            return []
        if not isinstance(raw, list):
            return []

        valid: list[ChatCitation] = []
        seen: set[uuid.UUID] = set()
        for item in raw:
            if not isinstance(item, dict):
                continue
            source = item.get("source")
            chunk_id = item.get("chunk_id")
            if isinstance(source, bool) or not isinstance(source, int):
                continue
            expected = citation_map.get(source)
            try:
                parsed_chunk_id = uuid.UUID(str(chunk_id))
            except (TypeError, ValueError):
                continue
            if expected is None or expected.chunk_id != parsed_chunk_id:
                continue
            if expected.chunk_id not in seen:
                valid.append(expected)
                seen.add(expected.chunk_id)
        return valid


async def _create_trace(
    session: AsyncSession,
    deps: Dependencies,
    course_id: uuid.UUID,
    version_id: uuid.UUID,
    query: str,
    pack: EvidencePack,
    *,
    stream_state: str,
) -> uuid.UUID:
    trace_id = uuid.uuid4()
    trace = RetrievalTrace(
        id=trace_id,
        request_id=str(trace_id),
        course_id=course_id,
        content_version_id=version_id,
        query=query,
        candidate_ids=[chunk.chunk_id for chunk in pack.candidates],
        reranked_ids=[chunk.chunk_id for chunk in pack.evidence],
        scores=[chunk.score for chunk in pack.candidates],
        timings_ms={
            **pack.timings_ms,
            "stream_state": stream_state,
            "retrieval_policy": "typed-scope-dense-lexical-rescore-v2",
            "reranker_policy": "scope-aware-score-diversity-v2",
            "chat_model": deps.settings.llm_chat_model,
            "embedding_model": deps.settings.llm_embedding_model,
            "minimum_relevance_score": MIN_RELEVANCE_SCORE,
            "high_confidence_relevance_score": HIGH_CONFIDENCE_RELEVANCE_SCORE,
            "evidence_token_budget": MAX_EVIDENCE_TOKENS,
        },
    )
    session.add(trace)
    await session.commit()
    return trace_id


async def _finish_trace(
    deps: Dependencies,
    trace_id: uuid.UUID,
    *,
    stream_state: str,
    generation_ms: float,
    answer_tokens: int,
    error: str | None = None,
) -> None:
    async with AsyncSession(deps.engine, expire_on_commit=False) as trace_session:
        trace = await trace_session.get(RetrievalTrace, trace_id)
        if trace is None:
            return
        trace.timings_ms = {
            **trace.timings_ms,
            "stream_state": stream_state,
            "generation_ms": round(generation_ms, 2),
            "answer_tokens": answer_tokens,
            **({"stream_error": error} if error else {}),
        }
        await trace_session.commit()


def _sse(event: str, data: dict[str, Any]) -> str:
    return f"event: {event}\ndata: {json.dumps(data)}\n\n"


@router.post("/{course_id}/chat", operation_id="streamCourseChat")
async def chat(
    session: Annotated[AsyncSession, Depends(get_session)],
    deps: Annotated[Dependencies, Depends(dependencies_from_request)],
    principal: Annotated[Principal, Depends(get_current_principal)],
    body: ChatRequest = Body(Ellipsis),
    course_id: uuid.UUID = Path(Ellipsis),
) -> StreamingResponse:
    request_started = time.perf_counter()
    course = await session.get(Course, course_id)
    if (
        course is None
        or course.tenant_id != principal.tenant_id
        or not principal_can_access_course(principal, course_id)
    ):
        raise HTTPException(status_code=status.HTTP_404_NOT_FOUND, detail="course not found")

    await RedisRateLimiter(deps.redis).enforce(
        f"chat:{principal.tenant_id}:{principal.user_id}", limit=60, window_seconds=60
    )
    version_id = course.active_content_version_id
    if version_id is None:
        raise HTTPException(status_code=400, detail="course has no active content version")
    version = await session.get(ContentVersion, version_id)
    if version is None or version.status != ContentVersionStatus.PUBLISHED:
        raise HTTPException(status_code=400, detail="active content version is not published")
    source_result = await session.execute(
        select(ContentVersionSource.source_id).where(ContentVersionSource.version_id == version_id)
    )
    source_ids = tuple(source_result.scalars().all())

    policy = teaching_policy_for(course, body)
    conversation: ConversationContext | None = None
    if getattr(deps, "engine", None) is not None:
        try:
            conversation = await prepare_conversation(
                session, principal, course, body, deps.settings
            )
        except ValueError as exc:
            raise HTTPException(status_code=404, detail="chat session not found") from exc

    pack = await _build_evidence_pack(
        retrieval_service=_get_retrieval_service(deps),
        reranker=_get_reranker(),
        tenant_id=principal.tenant_id,
        course_id=course_id,
        version_id=version_id,
        source_ids=source_ids,
        access_label=principal.access_label,
        query=body.query,
        service_name=deps.settings.service_name,
    )
    pack = _apply_teaching_policy(pack, policy, body)
    stream_state = "started" if pack.evidence else "abstained"
    trace_id = await _create_trace(
        session, deps, course_id, version_id, body.query, pack, stream_state=stream_state
    )

    stream: AsyncGenerator[str, None]
    if not pack.evidence:
        stream = _abstention_stream(deps, trace_id, conversation, request_started=request_started)
    else:
        stream = _event_stream(
            deps,
            trace_id,
            body,
            pack,
            conversation=conversation,
            request_started=request_started,
            teaching_directive=build_teaching_directive(
                policy,
                assessment_mode=body.assessment_mode,
                attempt_number=body.attempt_number,
            ),
        )
    return StreamingResponse(
        stream,
        media_type="text/event-stream",
        headers={"Cache-Control": "no-cache", "X-Accel-Buffering": "no"},
    )


async def _abstention_stream(
    deps: Dependencies,
    trace_id: uuid.UUID,
    conversation: ConversationContext | None,
    *,
    request_started: float | None = None,
) -> AsyncGenerator[str, None]:
    reason = "retrieval score below grounded-answer threshold"
    observe_chat_ttft(
        getattr(getattr(deps, "settings", None), "service_name", "agent-api"),
        "abstained",
        time.perf_counter() - (request_started or time.perf_counter()),
    )
    yield _sse("abstained", {"reason": reason})
    if conversation is not None and getattr(deps, "engine", None) is not None:
        await persist_assistant_turn(deps.engine, conversation.session_id, f"Abstained: {reason}")
    yield _sse(
        "done",
        {
            "trace_id": str(trace_id),
            "answer_tokens": 0,
            "session_id": str(conversation.session_id) if conversation else None,
        },
    )


async def _event_stream(
    deps: Dependencies,
    trace_id: uuid.UUID,
    body: ChatRequest,
    pack: EvidencePack,
    *,
    conversation: ConversationContext | None = None,
    request_started: float | None = None,
    teaching_directive: str | None = None,
) -> AsyncGenerator[str, None]:
    parser = CitationTrailerParser()
    answer_parts: list[str] = []
    started = time.perf_counter()
    terminal_state = "completed"
    error_detail: str | None = None
    cancelled = False
    first_event_recorded = False

    def record_first_event(outcome: str) -> None:
        nonlocal first_event_recorded
        if first_event_recorded:
            return
        observe_chat_ttft(
            getattr(getattr(deps, "settings", None), "service_name", "agent-api"),
            outcome,
            time.perf_counter() - (request_started or started),
        )
        first_event_recorded = True

    try:
        provider_stream = deps.llm.stream_chat(
            _build_prompt(body.query, pack.evidence, conversation, teaching_directive)
        )
        async for provider_token in provider_stream:
            for visible in parser.feed(provider_token):
                answer_parts.append(visible)
                record_first_event("token")
                yield _sse("token", {"text": visible})
        if tail := parser.finish_visible():
            answer_parts.append(tail)
            record_first_event("token")
            yield _sse("token", {"text": tail})
        for citation in parser.validated_citations(pack.citation_map):
            record_first_event("citation")
            yield _sse("citation", citation.model_dump(mode="json"))
    except (asyncio.CancelledError, GeneratorExit):
        terminal_state = "cancelled"
        cancelled = True
        raise
    except Exception as exc:
        terminal_state = "failed"
        error_detail = type(exc).__name__
        logger.error("chat_stream_failed", trace_id=str(trace_id), exc=str(exc))
        record_first_event("error")
        yield _sse("error", {"detail": "stream failed"})
    finally:
        answer_tokens = _estimate_tokens("".join(answer_parts))
        finish_task = asyncio.create_task(
            _finish_trace(
                deps,
                trace_id,
                stream_state=terminal_state,
                generation_ms=(time.perf_counter() - started) * 1000,
                answer_tokens=answer_tokens,
                error=error_detail,
            )
        )
        try:
            await asyncio.shield(finish_task)
        except asyncio.CancelledError:
            await finish_task
            raise
        if conversation is not None and getattr(deps, "engine", None) is not None:
            await persist_assistant_turn(
                deps.engine, conversation.session_id, "".join(answer_parts)
            )

    if not cancelled:
        record_first_event("done")
        yield _sse(
            "done",
            {
                "trace_id": str(trace_id),
                "answer_tokens": _estimate_tokens("".join(answer_parts)),
                "session_id": str(conversation.session_id) if conversation else None,
            },
        )
