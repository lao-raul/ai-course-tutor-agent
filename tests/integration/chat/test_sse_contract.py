from __future__ import annotations

import uuid
from collections.abc import AsyncIterator
from types import SimpleNamespace

import httpx
from fastapi import FastAPI

from course_tutor_api.auth import Principal, get_current_principal
from course_tutor_api.db import ContentVersion, Course
from course_tutor_api.dependencies import dependencies_from_request, get_session
from course_tutor_api.routes import chat as chat_route
from course_tutor_contracts.enums import (
    AccessLabel,
    AnchorType,
    ChunkClass,
    ContentVersionStatus,
    UserRole,
)
from course_tutor_contracts.retrieval import RetrievalResult, RetrievedChunk
from course_tutor_shared import Settings
from course_tutor_shared.config import Environment


class _Session:
    def __init__(
        self,
        tenant_id: uuid.UUID,
        course_id: uuid.UUID,
        version_id: uuid.UUID,
        source_id: uuid.UUID,
    ) -> None:
        self.course = SimpleNamespace(
            id=course_id,
            tenant_id=tenant_id,
            active_content_version_id=version_id,
        )
        self.version = SimpleNamespace(id=version_id, status=ContentVersionStatus.PUBLISHED)
        self.source_id = source_id
        self.traces: list[object] = []

    async def get(self, model: object, _identifier: object) -> object:
        return self.course if model is Course else self.version if model is ContentVersion else None

    async def execute(self, _statement: object) -> object:
        return SimpleNamespace(scalars=lambda: SimpleNamespace(all=lambda: [self.source_id]))

    def add(self, value: object) -> None:
        self.traces.append(value)

    async def commit(self) -> None:
        return None


class _Redis:
    async def incr(self, _key: str) -> int:
        return 1

    async def expire(self, _key: str, _seconds: int) -> None:
        return None


class _LLM:
    embedding_dimension = 8

    def __init__(self, chunk_id: uuid.UUID) -> None:
        self.chunk_id = chunk_id

    async def stream_chat(self, _messages, *, temperature: float = 0.2):  # type: ignore[no-untyped-def]
        yield "A grounded answer [Source 1].\nCI"
        yield f'TATIONS:[{{"source":1,"chunk_id":"{self.chunk_id}"}}]'


class _Retrieval:
    def __init__(self, chunk: RetrievedChunk) -> None:
        self.chunk = chunk

    async def search(self, **_kwargs: object) -> RetrievalResult:
        return RetrievalResult(
            candidates=[self.chunk], total_indexed=1, timings_ms={"dense_query_ms": 1.0}
        )


class _Reranker:
    def rerank(
        self,
        candidates: list[RetrievedChunk],
        *,
        max_from_same_source: int | None = None,
    ) -> list[RetrievedChunk]:
        del max_from_same_source
        return candidates


async def test_chat_sse_contract_orders_visible_tokens_citations_and_done(monkeypatch) -> None:  # type: ignore[no-untyped-def]
    tenant_id, course_id, version_id = uuid.uuid4(), uuid.uuid4(), uuid.uuid4()
    chunk = RetrievedChunk(
        chunk_id=uuid.uuid4(),
        source_id=uuid.uuid4(),
        text="Bayes theorem course content",
        relative_path="week-2/slides.pdf",
        mime_type="application/pdf",
        anchor_type=AnchorType.SLIDE,
        anchor_value="12",
        chunk_class=ChunkClass.CONTENT,
        score=0.91,
    )
    session = _Session(tenant_id, course_id, version_id, chunk.source_id)
    settings = Settings(environment=Environment.TEST)
    dependencies = SimpleNamespace(settings=settings, redis=_Redis(), llm=_LLM(chunk.chunk_id))
    principal = Principal(
        user_id=uuid.uuid4(),
        tenant_id=tenant_id,
        role=UserRole.STUDENT,
        access_label=AccessLabel.ENROLLED,
        subject="student",
        course_ids=frozenset({course_id}),
    )

    app = FastAPI()
    app.include_router(chat_route.router)
    app.state.dependencies = dependencies

    async def session_override() -> AsyncIterator[_Session]:
        yield session

    async def principal_override() -> Principal:
        return principal

    async def finish(*_args: object, **_kwargs: object) -> None:
        return None

    app.dependency_overrides[get_session] = session_override
    app.dependency_overrides[get_current_principal] = principal_override
    app.dependency_overrides[dependencies_from_request] = lambda: dependencies
    monkeypatch.setattr(chat_route, "_get_retrieval_service", lambda _deps: _Retrieval(chunk))
    monkeypatch.setattr(chat_route, "_get_reranker", _Reranker)
    monkeypatch.setattr(chat_route, "_finish_trace", finish)

    async with httpx.AsyncClient(
        transport=httpx.ASGITransport(app=app), base_url="http://test"
    ) as client:
        response = await client.post(
            f"/v1/courses/{course_id}/chat", json={"query": "Explain Bayes theorem"}
        )

    assert response.status_code == 200
    assert "CITATIONS:" not in response.text
    assert response.text.index("event: token") < response.text.index("event: citation")
    assert response.text.index("event: citation") < response.text.index("event: done")
    assert str(chunk.chunk_id) in response.text
    assert len(session.traces) == 1
