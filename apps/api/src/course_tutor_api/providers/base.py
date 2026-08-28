"""Provider protocols.

Kept narrow on purpose: the orchestrator should be able to run against a fake with no
network, and swapping LM Studio for another OpenAI-compatible host must not touch
call sites.
"""

from __future__ import annotations

from collections.abc import AsyncIterator, Sequence
from dataclasses import dataclass
from typing import Literal, Protocol, runtime_checkable


class ProviderError(RuntimeError):
    """Raised when an upstream provider fails, times out or is misconfigured."""


@dataclass(frozen=True, slots=True)
class ChatMessage:
    role: Literal["system", "user", "assistant"]
    content: str


@runtime_checkable
class EmbeddingProvider(Protocol):
    """Embeds text for indexing and retrieval."""

    @property
    def embedding_dimension(self) -> int:
        """Vector width this provider produces. Must match the Qdrant collection."""
        ...

    async def embed(self, texts: Sequence[str]) -> list[list[float]]: ...


@runtime_checkable
class LLMProvider(EmbeddingProvider, Protocol):
    """Streaming chat plus embeddings behind one OpenAI-compatible surface."""

    # Not ``async def``: implementations are async generators, so the method itself
    # returns the iterator rather than a coroutine yielding one.
    def stream_chat(
        self, messages: Sequence[ChatMessage], *, temperature: float = 0.2
    ) -> AsyncIterator[str]: ...

    async def health(self) -> None:
        """Raise :class:`ProviderError` when the provider is unusable."""
        ...


@runtime_checkable
class ObjectStore(Protocol):
    """Stores source originals and extraction artifacts."""

    async def put(self, key: str, data: bytes, *, content_type: str) -> str: ...

    async def get(self, key: str) -> bytes: ...

    async def health(self) -> None: ...
