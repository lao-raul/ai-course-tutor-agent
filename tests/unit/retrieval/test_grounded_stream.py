from __future__ import annotations

import asyncio
import json
import uuid
from types import SimpleNamespace

from course_tutor_api.routes import chat as chat_route
from course_tutor_api.routes.chat import (
    CitationTrailerParser,
    EvidencePack,
    _build_evidence_pack,
    _event_stream,
)
from course_tutor_contracts.enums import AccessLabel, AnchorType, ChunkClass
from course_tutor_contracts.retrieval import (
    ChatCitation,
    ChatRequest,
    RetrievalResult,
    RetrievedChunk,
)


def _chunk(path: str, score: float, text: str = "grounded material") -> RetrievedChunk:
    return RetrievedChunk(
        chunk_id=uuid.uuid4(),
        source_id=uuid.uuid4(),
        text=text,
        relative_path=path,
        mime_type="text/plain",
        anchor_type=AnchorType.PAGE,
        anchor_value="1",
        chunk_class=ChunkClass.CONTENT,
        score=score,
    )


class _Retrieval:
    def __init__(self, candidates: list[RetrievedChunk]) -> None:
        self.candidates = candidates

    async def search(self, **_kwargs: object) -> RetrievalResult:
        return RetrievalResult(
            candidates=self.candidates,
            total_indexed=len(self.candidates),
            timings_ms={"dense_query_ms": 4.2},
        )


class _ReverseReranker:
    def rerank(self, candidates: list[RetrievedChunk]) -> list[RetrievedChunk]:
        return list(reversed(candidates))


async def test_source_numbers_are_assigned_after_final_rerank() -> None:
    first, second = _chunk("first.pdf", 0.7), _chunk("second.pdf", 0.8)
    pack = await _build_evidence_pack(
        _Retrieval([first, second]),
        _ReverseReranker(),
        uuid.uuid4(),
        uuid.uuid4(),
        uuid.uuid4(),
        AccessLabel.ENROLLED,
        "question",
    )
    assert pack.evidence == (second, first)
    assert pack.citation_map[1].chunk_id == second.chunk_id
    assert pack.citation_map[2].chunk_id == first.chunk_id


async def test_low_scores_abstain_and_evidence_has_hard_token_budget() -> None:
    low = _chunk("low.pdf", 0.19)
    low_pack = await _build_evidence_pack(
        _Retrieval([low]),
        _ReverseReranker(),
        uuid.uuid4(),
        uuid.uuid4(),
        uuid.uuid4(),
        AccessLabel.ENROLLED,
        "unrelated question",
    )
    assert low_pack.evidence == ()

    huge = _chunk("huge.pdf", 0.9, "x" * 20_000)
    pack = await _build_evidence_pack(
        _Retrieval([huge]),
        _ReverseReranker(),
        uuid.uuid4(),
        uuid.uuid4(),
        uuid.uuid4(),
        AccessLabel.ENROLLED,
        "question",
    )
    assert len(pack.evidence) == 1
    assert pack.evidence[0].chunk_id == huge.chunk_id
    assert len(pack.evidence[0].text) <= chat_route.MAX_EVIDENCE_TOKENS * 4


def test_split_control_trailer_is_hidden_and_chunk_id_is_validated() -> None:
    chunk = _chunk("week-1.pdf", 0.9)
    citation = ChatCitation(
        chunk_id=chunk.chunk_id,
        relative_path=chunk.relative_path,
        anchor_type=chunk.anchor_type,
        anchor_value=chunk.anchor_value,
        text_excerpt=chunk.text,
    )
    parser = CitationTrailerParser()
    visible: list[str] = []
    for token in [
        "Bayes rule [Source 1].\nCITA",
        "TIONS:",
        json.dumps(
            [
                {"source": 1, "chunk_id": str(chunk.chunk_id)},
                {"source": 1, "chunk_id": str(uuid.uuid4())},
                {"source": 99, "chunk_id": str(chunk.chunk_id)},
            ]
        ),
    ]:
        visible.extend(parser.feed(token))
    visible.append(parser.finish_visible())
    assert "".join(visible) == "Bayes rule [Source 1].\n"
    assert "CITATIONS:" not in "".join(visible)
    assert parser.validated_citations({1: citation}) == [citation]


class _ControlledProvider:
    embedding_dimension = 8

    def __init__(self, chunk_id: uuid.UUID) -> None:
        self.release = asyncio.Event()
        self.chunk_id = chunk_id

    async def stream_chat(self, _messages, *, temperature: float = 0.2):  # type: ignore[no-untyped-def]
        yield "First token "
        await self.release.wait()
        yield f'CITATIONS:[{{"source":1,"chunk_id":"{self.chunk_id}"}}]'


def _pack(chunk: RetrievedChunk) -> EvidencePack:
    citation = ChatCitation(
        chunk_id=chunk.chunk_id,
        relative_path=chunk.relative_path,
        anchor_type=chunk.anchor_type,
        anchor_value=chunk.anchor_value,
        text_excerpt=chunk.text,
    )
    return EvidencePack(
        candidates=(chunk,),
        evidence=(chunk,),
        citation_map={1: citation},
        timings_ms={},
    )


async def test_first_sse_token_arrives_before_provider_completes(monkeypatch) -> None:  # type: ignore[no-untyped-def]
    chunk = _chunk("source.pdf", 0.9)
    provider = _ControlledProvider(chunk.chunk_id)
    states: list[str] = []

    async def finish(_deps, _trace_id, **kwargs):  # type: ignore[no-untyped-def]
        states.append(kwargs["stream_state"])

    monkeypatch.setattr(chat_route, "_finish_trace", finish)
    stream = _event_stream(
        SimpleNamespace(llm=provider, engine=None),  # type: ignore[arg-type]
        uuid.uuid4(),
        ChatRequest(query="question"),
        _pack(chunk),
    )
    first_event = await anext(stream)
    assert 'event: token\ndata: {"text": "First token "}' in first_event
    assert not provider.release.is_set()

    provider.release.set()
    remaining = "".join([event async for event in stream])
    assert "CITATIONS:" not in remaining
    assert "event: citation" in remaining
    assert states == ["completed"]


async def test_stream_close_records_cancelled_terminal_state(monkeypatch) -> None:  # type: ignore[no-untyped-def]
    chunk = _chunk("source.pdf", 0.9)
    provider = _ControlledProvider(chunk.chunk_id)
    states: list[str] = []

    async def finish(_deps, _trace_id, **kwargs):  # type: ignore[no-untyped-def]
        states.append(kwargs["stream_state"])

    monkeypatch.setattr(chat_route, "_finish_trace", finish)
    stream = _event_stream(
        SimpleNamespace(llm=provider, engine=None),  # type: ignore[arg-type]
        uuid.uuid4(),
        ChatRequest(query="question"),
        _pack(chunk),
    )
    await anext(stream)
    await stream.aclose()
    assert states == ["cancelled"]
