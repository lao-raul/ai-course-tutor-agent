"""Shared fixtures.

The suite must pass with no NAS and no LM Studio (design-spec Phase 0 exit), so every
fixture here is either in-memory or a fake.
"""

from __future__ import annotations

import os
from collections.abc import AsyncIterator, Iterator

import httpx
import pytest
from httpx import ASGITransport, AsyncClient
from sqlalchemy.ext.asyncio import (
    AsyncEngine,
    AsyncSession,
    async_sessionmaker,
    create_async_engine,
)

from course_tutor_api.app import create_app
from course_tutor_api.auth import create_auth_provider
from course_tutor_api.db import Base
from course_tutor_api.dependencies import Dependencies
from course_tutor_api.providers import FakeLLMProvider, FakeObjectStore
from course_tutor_shared import Settings, get_settings
from course_tutor_shared.config import Environment
from tests.support.postgres import reset_test_schema


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
        qdrant_client=None,  # type: ignore[arg-type]
        auth=create_auth_provider(settings),
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


@pytest.fixture
async def integration_db_engine() -> AsyncIterator[AsyncEngine]:
    """Disposable, explicitly marked PostgreSQL used by integration/e2e tests."""
    dsn = os.environ.get("TEST_POSTGRES_DSN")
    if not dsn:
        pytest.skip("TEST_POSTGRES_DSN is required; use scripts/run-integration-tests.sh")
    engine = create_async_engine(dsn)
    await reset_test_schema(engine, dsn)
    async with engine.begin() as connection:
        await connection.run_sync(Base.metadata.create_all)
    try:
        yield engine
    finally:
        await engine.dispose()


@pytest.fixture
async def db_session(integration_db_engine: AsyncEngine) -> AsyncIterator[AsyncSession]:
    maker = async_sessionmaker(integration_db_engine, expire_on_commit=False)
    async with maker() as session:
        yield session
