from __future__ import annotations

from types import SimpleNamespace
from unittest.mock import AsyncMock, Mock

from course_tutor_api.auth import create_auth_provider
from course_tutor_api.dependencies import Dependencies, dependencies_from_request
from course_tutor_api.providers import FakeLLMProvider
from course_tutor_shared import Settings


async def test_lifespan_clients_close_exactly_once(settings: Settings) -> None:
    redis = SimpleNamespace(aclose=AsyncMock())
    http = SimpleNamespace(aclose=AsyncMock())
    engine = SimpleNamespace(dispose=AsyncMock())
    qdrant = SimpleNamespace(close=Mock())
    llm = FakeLLMProvider(embedding_dimension=8)
    llm.aclose = AsyncMock()  # type: ignore[attr-defined,method-assign]
    dependencies = Dependencies(
        settings=settings,
        engine=engine,  # type: ignore[arg-type]
        redis=redis,  # type: ignore[arg-type]
        http=http,  # type: ignore[arg-type]
        llm=llm,
        qdrant_client=qdrant,  # type: ignore[arg-type]
        auth=create_auth_provider(settings),
    )
    request = SimpleNamespace(app=SimpleNamespace(state=SimpleNamespace(dependencies=dependencies)))

    assert dependencies_from_request(request) is dependencies  # type: ignore[arg-type]
    assert dependencies_from_request(request) is dependencies  # type: ignore[arg-type]
    await dependencies.aclose()

    redis.aclose.assert_awaited_once()
    http.aclose.assert_awaited_once()
    engine.dispose.assert_awaited_once()
    qdrant.close.assert_called_once()
    llm.aclose.assert_awaited_once()  # type: ignore[attr-defined]
