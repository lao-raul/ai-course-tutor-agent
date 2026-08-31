"""Chat endpoint: RAG-grounded SSE streaming responses."""

from __future__ import annotations

import json
import uuid
from collections.abc import AsyncGenerator
from typing import Annotated, Any

import structlog
from fastapi import APIRouter, Depends, HTTPException, status
from fastapi.responses import StreamingResponse
from sqlalchemy.ext.asyncio import AsyncSession

from course_tutor_api.db import ContentVersion, Course, RetrievalTrace
from course_tutor_api.dependencies import Dependencies, get_dependencies
from course_tutor_contracts.enums import AccessLabel, ContentVersionStatus
from course_tutor_contracts.retrieval import (
    ChatCitation,
    ChatRequest,
    RetrievedChunk,
)

router = APIRouter(prefix="/v1/courses", tags=["chat"])
logger = structlog.get_logger(__name__)

MAX_EVIDENCE_CHUNKS = 5
SCORE_THRESHOLD = 0.3


# Lazy import types to avoid circular dependency at import time.
# chat → course_tutor_retrieval.search → course_tutor_api.providers.base → course_tutor_api


def _get_retrieval_service(
    deps: Dependencies,
) -> Any:  # HybridRetrievalService — lazy to avoid circular import
    from course_tutor_retrieval.search import HybridRetrievalService

    return HybridRetrievalService(
        qdrant_client=deps.qdrant_client,
        embed_provider=deps.llm,
    )


def _get_reranker() -> Any:  # Reranker — lazy to avoid circular import
    from course_tutor_retrieval.reranker import Reranker

    return Reranker()


async def _build_evidence_pack(
    retrieval_service: Any,  # HybridRetrievalService
    reranker: Any,  # Reranker
    session: AsyncSession,
    course_id: uuid.UUID,
    version_id: uuid.UUID,
    access_label: AccessLabel,
    query: str,
) -> tuple[list[RetrievedChunk], list[ChatCitation]]:
    """Run retrieval and return evidence chunks + built citations."""
    result = await retrieval_service.search(
        query=query,
        course_id=course_id,
        content_version_id=version_id,
        access_label=access_label,
        limit=20,
    )
    if not result.candidates:
        return [], []

    reranked = reranker.rerank(result.candidates)
    evidence = reranked[:MAX_EVIDENCE_CHUNKS]

    citations = []
    for chunk in evidence:
        citations.append(
            ChatCitation(
                chunk_id=chunk.chunk_id,
                relative_path=chunk.relative_path,
                anchor_type=chunk.anchor_type,
                anchor_value=chunk.anchor_value,
                text_excerpt=chunk.text[:200],
            )
        )

    return evidence, citations


def _build_prompt(query: str, evidence: list[RetrievedChunk]) -> list[dict[str, str]]:
    """Build the chat prompt with evidence context."""
    if not evidence:
        return [
            {
                "role": "system",
                "content": (
                    "You are a helpful course teaching assistant. "
                    "Answer the student's question based only on the provided course material. "
                    "If the material does not contain enough information to answer, "
                    "say so clearly and suggest how the student might find the answer."
                ),
            },
            {"role": "user", "content": query},
        ]

    evidence_lines = []
    for i, chunk in enumerate(evidence, 1):
        evidence_lines.append(
            f"[Source {i}] ({chunk.relative_path}, "
            f"{chunk.anchor_type.value} {chunk.anchor_value}):\n{chunk.text}"
        )
    evidence_context = "\n\n".join(evidence_lines)

    system_msg = (
        "You are a helpful course teaching assistant. "
        "Answer the student's question based ONLY on the provided course material. "
        "For each claim, cite the source using [Source N] notation where N is the number. "
        "If the material does not contain enough information, say so clearly. "
        "Do not make up information not present in the course material. "
        "After your answer, on a new line output exactly: "
        "CITATIONS:"
        + json.dumps(
            [{"source": i + 1, "chunk_id": str(c.chunk_id)} for i, c in enumerate(evidence)]
        )
    )

    return [
        {"role": "system", "content": system_msg},
        {
            "role": "user",
            "content": f"Course material:\n{evidence_context}\n\nQuestion: {query}",
        },
    ]


async def _parse_stream(
    stream: Any,
    evidence: list[RetrievedChunk],
) -> tuple[str, list[dict[str, Any]]]:
    """Consume the token stream, extract citations, return full text + citation list."""
    full_text = ""
    buffer = ""
    citations_raw: list[dict[str, Any]] = []

    async for token in stream:
        full_text += token
        buffer += token

        if "CITATIONS:" in buffer:
            parts = buffer.split("CITATIONS:", 1)
            body = parts[0]
            remainder = parts[1].strip()
            try:
                citations_raw = json.loads(remainder)
            except json.JSONDecodeError:
                pass
            full_text = body
            break

    return full_text, citations_raw


@router.post("/{course_id}/chat")
async def chat(
    course_id: uuid.UUID,
    body: ChatRequest,
    session: Annotated[AsyncSession, Depends(get_session)],
    deps: Annotated[Dependencies, Depends(get_dependencies)],
) -> StreamingResponse:
    """Stream a RAG-grounded chat response with inline citations.

    Returns an SSE stream with events:
      - token: {"text": "..."}
      - citation: {"chunk_id": "...", "relative_path": "...", ...}
      - abstained: {"reason": "..."}
      - done: {"trace_id": "...", "answer_tokens": N}
    """
    course = await session.get(Course, course_id)
    if course is None:
        raise HTTPException(status_code=status.HTTP_404_NOT_FOUND, detail="course not found")

    version_id = course.active_content_version_id
    if version_id is None:
        raise HTTPException(
            status_code=status.HTTP_400_BAD_REQUEST,
            detail="course has no active content version",
        )

    version = await session.get(ContentVersion, version_id)
    if version is None or version.status != ContentVersionStatus.PUBLISHED:
        raise HTTPException(
            status_code=status.HTTP_400_BAD_REQUEST,
            detail="active content version is not published",
        )

    retrieval_service = _get_retrieval_service(deps)
    reranker = _get_reranker()

    evidence, citations = await _build_evidence_pack(
        retrieval_service=retrieval_service,
        reranker=reranker,
        session=session,
        course_id=course_id,
        version_id=version_id,
        access_label=body.access_label,
        query=body.query,
    )

    if not evidence:
        return StreamingResponse(
            _abstention_stream(),
            media_type="text/event-stream",
            headers={"Cache-Control": "no-cache"},
        )

    citation_map: dict[int, ChatCitation] = {i + 1: c for i, c in enumerate(citations)}

    return StreamingResponse(
        _event_stream(
            deps=deps,
            session=session,
            course_id=course_id,
            version_id=version_id,
            body=body,
            evidence=evidence,
            citation_map=citation_map,
        ),
        media_type="text/event-stream",
        headers={
            "Cache-Control": "no-cache",
            "X-Accel-Buffering": "no",
        },
    )


async def _abstention_stream() -> AsyncGenerator[str, None]:
    yield "event: abstained\ndata: "
    yield json.dumps({"reason": "no relevant content found for this query"})
    yield "\n\n"
    yield "event: done\ndata: "
    yield json.dumps({"trace_id": None, "answer_tokens": 0})
    yield "\n\n"


async def _event_stream(
    deps: Dependencies,
    session: AsyncSession,
    course_id: uuid.UUID,
    version_id: uuid.UUID,
    body: ChatRequest,
    evidence: list[RetrievedChunk],
    citation_map: dict[int, ChatCitation],
) -> AsyncGenerator[str, None]:
    trace_id = uuid.uuid4()
    answer_tokens = 0

    try:
        prompt_messages = _build_prompt(body.query, evidence)
        stream = deps.llm.stream_chat(prompt_messages)  # type: ignore[arg-type]
        full_text, citations_raw = await _parse_stream(stream, evidence)

        for char in full_text:
            yield f"event: token\ndata: {json.dumps({'text': char})}\n\n"
            answer_tokens += 1

        for cit_data in citations_raw:
            src_num = cit_data.get("source")
            if src_num and src_num in citation_map:
                cit = citation_map[src_num]
                yield (f"event: citation\ndata: {json.dumps(cit.model_dump(mode='json'))}\n\n")

    except Exception as exc:
        logger.error("chat_stream_failed", course_id=str(course_id), exc=str(exc))
        yield "event: error\ndata: "
        yield json.dumps({"detail": "stream failed"})
        yield "\n\n"

    yield "event: done\ndata: "
    yield json.dumps({"trace_id": str(trace_id), "answer_tokens": answer_tokens})
    yield "\n\n"

    try:
        trace = RetrievalTrace(
            id=trace_id,
            request_id=str(trace_id),
            course_id=course_id,
            content_version_id=version_id,
            query=body.query,
            candidate_ids=[c.chunk_id for c in evidence],
            reranked_ids=[c.chunk_id for c in evidence],
            scores=[c.score for c in evidence],
            timings_ms={"retrieval": sum(e.score for e in evidence) if evidence else 0},
        )
        session.add(trace)
        await session.commit()
    except Exception as exc:
        logger.warning("retrieval_trace_write_failed", exc=str(exc))


# ---------------------------------------------------------------------------
# Dependencies
# ---------------------------------------------------------------------------


async def get_session() -> AsyncGenerator[AsyncSession, None]:
    deps = get_dependencies()
    async with AsyncSession(deps.engine, expire_on_commit=False) as session:
        yield session
