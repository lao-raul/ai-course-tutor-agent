"""Bounded retry and circuit-breaker wrapper for inference providers."""

from __future__ import annotations

import asyncio
import time
from collections.abc import AsyncIterator, Sequence

from course_tutor_api.providers.base import ChatMessage, LLMProvider, ProviderError


class ResilientLLMProvider:
    """Retry transient failures and stop hammering an unhealthy local provider.

    A chat stream is retried only before its first visible token. Once output has
    started, replaying the request could duplicate text and is therefore unsafe.
    """

    def __init__(
        self,
        delegate: LLMProvider,
        *,
        max_attempts: int = 2,
        failure_threshold: int = 3,
        reset_seconds: float = 30.0,
        retry_delay_seconds: float = 0.05,
    ) -> None:
        self._delegate = delegate
        self._max_attempts = max_attempts
        self._failure_threshold = failure_threshold
        self._reset_seconds = reset_seconds
        self._retry_delay_seconds = retry_delay_seconds
        self._consecutive_failures = 0
        self._opened_at: float | None = None

    @property
    def embedding_dimension(self) -> int:
        return self._delegate.embedding_dimension

    def _ensure_closed(self) -> None:
        if self._opened_at is None:
            return
        if time.monotonic() - self._opened_at >= self._reset_seconds:
            self._opened_at = None
            self._consecutive_failures = 0
            return
        raise ProviderError("inference provider circuit is open")

    def _success(self) -> None:
        self._consecutive_failures = 0
        self._opened_at = None

    def _failure(self) -> None:
        self._consecutive_failures += 1
        if self._consecutive_failures >= self._failure_threshold:
            self._opened_at = time.monotonic()

    async def _backoff(self) -> None:
        if self._retry_delay_seconds:
            await asyncio.sleep(self._retry_delay_seconds)

    async def embed(self, texts: Sequence[str]) -> list[list[float]]:
        last_error: ProviderError | None = None
        for attempt in range(self._max_attempts):
            self._ensure_closed()
            try:
                result = await self._delegate.embed(texts)
            except ProviderError as exc:
                last_error = exc
                self._failure()
                if attempt + 1 < self._max_attempts:
                    await self._backoff()
                continue
            self._success()
            return result
        raise last_error or ProviderError("embedding provider failed")

    async def stream_chat(
        self, messages: Sequence[ChatMessage], *, temperature: float = 0.2
    ) -> AsyncIterator[str]:
        last_error: ProviderError | None = None
        for attempt in range(self._max_attempts):
            self._ensure_closed()
            emitted = False
            try:
                async for token in self._delegate.stream_chat(messages, temperature=temperature):
                    emitted = True
                    yield token
            except ProviderError as exc:
                last_error = exc
                self._failure()
                if emitted or attempt + 1 >= self._max_attempts:
                    raise
                await self._backoff()
                continue
            self._success()
            return
        raise last_error or ProviderError("chat provider failed")

    async def health(self) -> None:
        self._ensure_closed()
        await self._delegate.health()

    async def aclose(self) -> None:
        if (close := getattr(self._delegate, "aclose", None)) is not None:
            await close()
