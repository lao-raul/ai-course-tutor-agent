"""Provider adapters.

The LM Studio tests use a mock transport rather than the live host, so they run in CI
and still pin the two behaviours the spec calls out: fail-closed on an embedding
dimension mismatch, and a health check that verifies the models are actually loaded.
"""

from __future__ import annotations

import json

import httpx
import pytest

from course_tutor_api.providers import (
    ChatMessage,
    EmbeddingProvider,
    FakeLLMProvider,
    FakeObjectStore,
    LLMProvider,
    LMStudioProvider,
    ProviderError,
)
from course_tutor_shared import Settings


def _provider(settings: Settings, handler) -> LMStudioProvider:  # type: ignore[no-untyped-def]
    client = httpx.AsyncClient(
        transport=httpx.MockTransport(handler), base_url=settings.llm_base_url
    )
    return LMStudioProvider(settings, client=client)


# --- Fakes satisfy the protocols ------------------------------------------------


def test_fake_provider_satisfies_protocols(fake_llm: FakeLLMProvider) -> None:
    assert isinstance(fake_llm, EmbeddingProvider)
    assert isinstance(fake_llm, LLMProvider)


async def test_fake_embeddings_are_deterministic_and_normalized(
    fake_llm: FakeLLMProvider,
) -> None:
    first = await fake_llm.embed(["week 3 bayesian networks"])
    second = await fake_llm.embed(["week 3 bayesian networks"])
    assert first == second
    assert len(first[0]) == 8
    assert pytest.approx(sum(v * v for v in first[0]), abs=1e-9) == 1.0


async def test_fake_embeddings_differ_across_inputs(fake_llm: FakeLLMProvider) -> None:
    [a], [b] = await fake_llm.embed(["alpha"]), await fake_llm.embed(["beta"])
    assert a != b


async def test_fake_embed_of_nothing_is_empty(fake_llm: FakeLLMProvider) -> None:
    assert await fake_llm.embed([]) == []


async def test_fake_object_store_round_trips(fake_object_store: FakeObjectStore) -> None:
    await fake_object_store.put("a/b.pdf", b"bytes", content_type="application/pdf")
    assert await fake_object_store.get("a/b.pdf") == b"bytes"
    with pytest.raises(ProviderError, match="object not found"):
        await fake_object_store.get("missing")


# --- LM Studio adapter ----------------------------------------------------------


async def test_embed_rejects_dimension_mismatch(settings: Settings) -> None:
    """Fail closed: an index built at the wrong width is silently unsearchable."""

    def handler(request: httpx.Request) -> httpx.Response:
        # settings fixture configures 8; return 4.
        return httpx.Response(200, json={"data": [{"embedding": [0.1, 0.2, 0.3, 0.4]}]})

    with pytest.raises(ProviderError, match="dimension mismatch"):
        await _provider(settings, handler).embed(["hello"])


async def test_embed_accepts_matching_dimension(settings: Settings) -> None:
    vector = [0.1] * 8

    def handler(request: httpx.Request) -> httpx.Response:
        payload = json.loads(request.content)
        assert payload["model"] == "test-embedding"
        return httpx.Response(200, json={"data": [{"embedding": vector}]})

    assert await _provider(settings, handler).embed(["hello"]) == [vector]


async def test_embed_wraps_transport_errors(settings: Settings) -> None:
    def handler(request: httpx.Request) -> httpx.Response:
        raise httpx.ConnectError("refused")

    with pytest.raises(ProviderError, match="embedding request failed"):
        await _provider(settings, handler).embed(["hello"])


async def test_health_requires_both_models_loaded(settings: Settings) -> None:
    def handler(request: httpx.Request) -> httpx.Response:
        return httpx.Response(200, json={"data": [{"id": "test-chat"}]})

    with pytest.raises(ProviderError, match=r"models not loaded.*test-embedding"):
        await _provider(settings, handler).health()


async def test_health_passes_when_models_present(settings: Settings) -> None:
    def handler(request: httpx.Request) -> httpx.Response:
        return httpx.Response(200, json={"data": [{"id": "test-chat"}, {"id": "test-embedding"}]})

    await _provider(settings, handler).health()


async def test_health_reports_unreachable_host(settings: Settings) -> None:
    def handler(request: httpx.Request) -> httpx.Response:
        raise httpx.ConnectTimeout("timed out")

    with pytest.raises(ProviderError, match="LM Studio unreachable"):
        await _provider(settings, handler).health()


async def test_stream_chat_yields_content_deltas(settings: Settings) -> None:
    chunks = [
        'data: {"choices":[{"delta":{"role":"assistant"}}]}',
        'data: {"choices":[{"delta":{"content":"Bayes"}}]}',
        'data: {"choices":[{"delta":{"content":" rule"}}]}',
        "data: [DONE]",
    ]

    def handler(request: httpx.Request) -> httpx.Response:
        assert json.loads(request.content)["stream"] is True
        return httpx.Response(200, text="\n".join(chunks))

    provider = _provider(settings, handler)
    tokens = [
        token async for token in provider.stream_chat([ChatMessage(role="user", content="hi")])
    ]
    assert tokens == ["Bayes", " rule"]
