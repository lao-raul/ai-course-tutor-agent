"""Deterministic test doubles.

Same output for the same input, no network. This is what lets the Phase 0 exit
criterion hold: the suite runs without NAS or LM Studio.
"""

from __future__ import annotations

import hashlib
import math
from collections.abc import AsyncIterator, Sequence

from course_tutor_api.providers.base import ChatMessage, ProviderError


class FakeLLMProvider:
    """Hash-seeded embeddings and a canned streaming reply."""

    def __init__(
        self,
        *,
        embedding_dimension: int = 1024,
        reply: str = "This is a deterministic fake answer.",
        healthy: bool = True,
    ) -> None:
        self._dimension = embedding_dimension
        self._reply = reply
        self.healthy = healthy
        self.embed_calls: list[list[str]] = []
        self.chat_calls: list[list[ChatMessage]] = []

    @property
    def embedding_dimension(self) -> int:
        return self._dimension

    async def embed(self, texts: Sequence[str]) -> list[list[float]]:
        self.embed_calls.append(list(texts))
        return [self._vector_for(text) for text in texts]

    def _vector_for(self, text: str) -> list[float]:
        """Stable unit vector derived from the text digest."""
        digest = hashlib.sha256(text.encode("utf-8")).digest()
        raw = [(digest[i % len(digest)] - 127.5) / 127.5 for i in range(self._dimension)]
        norm = math.sqrt(sum(value * value for value in raw)) or 1.0
        return [value / norm for value in raw]

    async def stream_chat(
        self, messages: Sequence[ChatMessage], *, temperature: float = 0.2
    ) -> AsyncIterator[str]:
        self.chat_calls.append(list(messages))
        if not self.healthy:
            raise ProviderError("fake provider is configured as unhealthy")
        for token in self._reply.split(" "):
            yield f"{token} "

    async def health(self) -> None:
        if not self.healthy:
            raise ProviderError("fake provider is configured as unhealthy")


class FakeObjectStore:
    """In-memory object store."""

    def __init__(self, *, healthy: bool = True) -> None:
        self.objects: dict[str, bytes] = {}
        self.content_types: dict[str, str] = {}
        self.healthy = healthy

    async def put(self, key: str, data: bytes, *, content_type: str) -> str:
        self.objects[key] = data
        self.content_types[key] = content_type
        return key

    async def get(self, key: str) -> bytes:
        try:
            return self.objects[key]
        except KeyError as exc:
            raise ProviderError(f"object not found: {key}") from exc

    async def health(self) -> None:
        if not self.healthy:
            raise ProviderError("fake object store is configured as unhealthy")
