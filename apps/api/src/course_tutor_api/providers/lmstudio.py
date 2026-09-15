"""LM Studio adapter (OpenAI-compatible).

Finite timeouts and an explicit dimension check are the point of this class: a hung
chat request or a dimension mismatch must surface as an error, not as a stalled stream
or a silently unusable index (function-spec §7.4, acceptance criterion 6).
"""

from __future__ import annotations

import json
from collections.abc import AsyncIterator, Sequence

import httpx

from course_tutor_api.providers.base import ChatMessage, ProviderError
from course_tutor_shared import Settings, get_logger, outbound_trace_headers, span

logger = get_logger(__name__)

# Connect fast, allow a long read for streamed generations, but never wait forever.
DEFAULT_TIMEOUT = httpx.Timeout(connect=5.0, read=120.0, write=10.0, pool=5.0)
HEALTH_TIMEOUT = httpx.Timeout(5.0)


class LMStudioProvider:
    """Chat + embeddings against ``LLM_BASE_URL``."""

    def __init__(self, settings: Settings, client: httpx.AsyncClient | None = None) -> None:
        self._settings = settings
        self._owns_client = client is None
        self._client = client or httpx.AsyncClient(
            base_url=settings.llm_base_url,
            timeout=DEFAULT_TIMEOUT,
            headers={"Authorization": f"Bearer {settings.llm_api_key.get_secret_value()}"},
        )

    @property
    def embedding_dimension(self) -> int:
        return int(self._settings.llm_embedding_dimension)

    async def embed(self, texts: Sequence[str]) -> list[list[float]]:
        if not texts:
            return []
        try:
            with span("llm.embed", **{"server.address": self._settings.llm_base_url}):
                response = await self._client.post(
                    "/embeddings",
                    json={"model": self._settings.llm_embedding_model, "input": list(texts)},
                    headers=outbound_trace_headers(),
                )
            response.raise_for_status()
        except httpx.HTTPError as exc:
            raise ProviderError(f"embedding request failed: {exc}") from exc

        vectors = [item["embedding"] for item in response.json()["data"]]
        expected = self.embedding_dimension
        for vector in vectors:
            if len(vector) != expected:
                # Fail closed: an index built at the wrong width is silently unsearchable.
                raise ProviderError(
                    f"embedding dimension mismatch: model "
                    f"{self._settings.llm_embedding_model} returned {len(vector)}, "
                    f"configured LLM_EMBEDDING_DIMENSION is {expected}"
                )
        return vectors

    async def stream_chat(
        self, messages: Sequence[ChatMessage], *, temperature: float = 0.2
    ) -> AsyncIterator[str]:
        payload = {
            "model": self._settings.llm_chat_model,
            "messages": [{"role": m.role, "content": m.content} for m in messages],
            "temperature": temperature,
            "stream": True,
        }
        try:
            with span("llm.chat", **{"server.address": self._settings.llm_base_url}):
                stream = self._client.stream(
                    "POST",
                    "/chat/completions",
                    json=payload,
                    headers=outbound_trace_headers(),
                )
            async with stream as response:
                response.raise_for_status()
                async for line in response.aiter_lines():
                    if not line.startswith("data: "):
                        continue
                    data = line.removeprefix("data: ").strip()
                    if data == "[DONE]":
                        return
                    delta = json.loads(data)["choices"][0].get("delta", {})
                    if content := delta.get("content"):
                        yield content
        except httpx.HTTPError as exc:
            raise ProviderError(f"chat stream failed: {exc}") from exc

    async def health(self) -> None:
        """Verify the host is reachable and both configured models are loaded."""
        try:
            response = await self._client.get(
                "/models", timeout=HEALTH_TIMEOUT, headers=outbound_trace_headers()
            )
            response.raise_for_status()
        except httpx.HTTPError as exc:
            raise ProviderError(f"LM Studio unreachable at {self._settings.llm_base_url}") from exc

        available = {model["id"] for model in response.json().get("data", [])}
        missing = {
            self._settings.llm_chat_model,
            self._settings.llm_embedding_model,
        } - available
        if missing:
            raise ProviderError(f"models not loaded in LM Studio: {sorted(missing)}")

    async def aclose(self) -> None:
        if self._owns_client:
            await self._client.aclose()
