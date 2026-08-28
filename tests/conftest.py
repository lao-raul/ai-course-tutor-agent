"""Shared fixtures.

The suite must pass with no NAS and no LM Studio (design-spec Phase 0 exit), so every
fixture here is either in-memory or a fake.
"""

from __future__ import annotations

from collections.abc import AsyncIterator, Iterator

import httpx
import pytest
from httpx import ASGITransport, AsyncClient

from course_tutor_api.app import create_app
from course_tutor_api.dependencies import Dependencies
from course_tutor_api.providers import FakeLLMProvider, FakeObjectStore
from course_tutor_shared import Settings, get_settings
from course_tutor_shared.config import Environment


@pytest.fixture(autouse=True)
def _clear_settings_cache() -> Iterator[None]:
    """Settings are process-cached; tests must not leak configuration into each other."""
    get_settings.cache_clear()
    yield
    get_settings.cache_clear()


@pytest.fixture
def settings() -> Settings:
    return Settings(
        environment=Environment.TEST,
        service_name="course-tutor-test",
        llm_base_url="http://llm.invalid/v1",
        llm_chat_model="test-chat",
        llm_embedding_model="test-embedding",
        llm_embedding_dimension=8,
        course_source_path=None,
    )


@pytest.fixture
def fake_llm() -> FakeLLMProvider:
    return FakeLLMProvider(embedding_dimension=8)


@pytest.fixture
def fake_object_store() -> FakeObjectStore:
    return FakeObjectStore()


class StubProbe:
    """Probe double: healthy unless given an error to raise."""

    def __init__(self, name: str, *, error: Exception | None = None) -> None:
        self.name = name
        self.error = error

    async def check(self) -> None:
        if self.error is not None:
            raise self.error


class LLMProbeDouble:
    """Delegates to the fake provider so tests can flip provider health at runtime."""

    name = "llm"

    def __init__(self, provider: FakeLLMProvider) -> None:
        self.provider = provider

    async def check(self) -> None:
        await self.provider.health()


@pytest.fixture
async def api_client(settings: Settings, fake_llm: FakeLLMProvider) -> AsyncIterator[AsyncClient]:
    """App wired to fakes.

    ``ASGITransport`` does not run the lifespan, so state is injected directly and no
    real Postgres/Redis/Qdrant client is ever constructed.
    """
    app = create_app(settings)
    http = httpx.AsyncClient()
    dependencies = Dependencies(
        settings=settings,
        engine=None,  # type: ignore[arg-type]
        redis=None,  # type: ignore[arg-type]
        http=http,
        llm=fake_llm,
        _probes=[
            StubProbe("postgres"),
            StubProbe("redis"),
            StubProbe("qdrant"),
            LLMProbeDouble(fake_llm),
        ],
    )
    app.state.settings = settings
    app.state.dependencies = dependencies

    async with AsyncClient(transport=ASGITransport(app=app), base_url="http://test") as client:
        yield client
    await http.aclose()
