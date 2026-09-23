"""Dependency container and health probes.

Readiness reports each backing store separately so an outage is attributable rather
than a generic 503 (function-spec acceptance criterion 6).
"""

from __future__ import annotations

import asyncio
import time
from collections.abc import AsyncGenerator
from dataclasses import dataclass, field
from typing import Protocol, cast

import httpx
from fastapi import HTTPException, Request, status
from qdrant_client import QdrantClient
from redis.asyncio import Redis
from sqlalchemy.ext.asyncio import AsyncEngine, AsyncSession, create_async_engine
from sqlalchemy.sql import text

from course_tutor_api.auth import AuthProvider, create_auth_provider
from course_tutor_api.providers import (
    LLMProvider,
    LMStudioProvider,
    ProviderError,
    ResilientLLMProvider,
)
from course_tutor_shared import Settings, get_logger, get_settings, observe_dependency, span

logger = get_logger(__name__)

PROBE_TIMEOUT_SECONDS = 5.0


@dataclass(frozen=True, slots=True)
class ProbeResult:
    name: str
    healthy: bool
    latency_ms: float
    detail: str | None = None


class Probe(Protocol):
    name: str

    async def check(self) -> None:
        """Return normally when healthy, raise otherwise."""
        ...


async def run_probe(probe: Probe) -> ProbeResult:
    started = time.perf_counter()
    try:
        async with asyncio.timeout(PROBE_TIMEOUT_SECONDS):
            await probe.check()
    except TimeoutError:
        return ProbeResult(
            name=probe.name,
            healthy=False,
            latency_ms=(time.perf_counter() - started) * 1000,
            detail=f"timed out after {PROBE_TIMEOUT_SECONDS}s",
        )
    except Exception as exc:
        return ProbeResult(
            name=probe.name,
            healthy=False,
            latency_ms=(time.perf_counter() - started) * 1000,
            detail=str(exc),
        )
    return ProbeResult(
        name=probe.name, healthy=True, latency_ms=(time.perf_counter() - started) * 1000
    )


@dataclass(slots=True)
class PostgresProbe:
    engine: AsyncEngine
    name: str = "postgres"

    async def check(self) -> None:
        async with self.engine.connect() as connection:
            await connection.execute(text("SELECT 1"))


@dataclass(slots=True)
class RedisProbe:
    client: Redis
    name: str = "redis"

    async def check(self) -> None:
        await self.client.ping()


@dataclass(slots=True)
class QdrantProbe:
    client: httpx.AsyncClient
    url: str
    name: str = "qdrant"

    async def check(self) -> None:
        response = await self.client.get(f"{self.url}/readyz")
        response.raise_for_status()


@dataclass(slots=True)
class MinioProbe:
    client: httpx.AsyncClient
    url: str
    name: str = "minio"

    async def check(self) -> None:
        response = await self.client.get(f"{self.url.rstrip('/')}/minio/health/ready")
        response.raise_for_status()


@dataclass(slots=True)
class LLMProbe:
    provider: LLMProvider
    name: str = "llm"

    async def check(self) -> None:
        await self.provider.health()


@dataclass(slots=True)
class Dependencies:
    """Owns long-lived clients for the process lifetime."""

    settings: Settings
    engine: AsyncEngine
    redis: Redis
    http: httpx.AsyncClient
    llm: LLMProvider
    qdrant_client: QdrantClient
    auth: AuthProvider
    _probes: list[Probe] = field(default_factory=list)

    def probes(self) -> list[Probe]:
        if not self._probes:
            self._probes = [
                PostgresProbe(self.engine),
                RedisProbe(self.redis),
                QdrantProbe(self.http, self.settings.qdrant_url),
                LLMProbe(self.llm),
            ]
            if self.settings.store_source_artifacts:
                self._probes.insert(-1, MinioProbe(self.http, self.settings.minio_endpoint))
        return self._probes

    async def readiness(self) -> list[ProbeResult]:
        with span("dependencies.readiness"):
            results = list(await asyncio.gather(*(run_probe(p) for p in self.probes())))
        for result in results:
            observe_dependency(
                self.settings.service_name,
                result.name,
                result.healthy,
                result.latency_ms,
            )
        return results

    async def aclose(self) -> None:
        await self.redis.aclose()
        await self.http.aclose()
        await self.engine.dispose()
        self.qdrant_client.close()
        if (close := getattr(self.llm, "aclose", None)) is not None:
            await close()


class RedisRateLimiter:
    def __init__(self, client: Redis) -> None:
        self._client = client

    async def enforce(self, key: str, *, limit: int, window_seconds: int) -> None:
        redis_key = f"rate-limit:{key}"
        count = await self._client.incr(redis_key)
        if count == 1:
            await self._client.expire(redis_key, window_seconds)
        if count > limit:
            raise HTTPException(
                status_code=status.HTTP_429_TOO_MANY_REQUESTS,
                detail="rate limit exceeded",
            )


def get_dependencies(settings: Settings | None = None) -> Dependencies:
    settings = settings or get_settings()
    http = httpx.AsyncClient(timeout=httpx.Timeout(PROBE_TIMEOUT_SECONDS))
    qdrant_client = QdrantClient(url=settings.qdrant_url)
    return Dependencies(
        settings=settings,
        engine=create_async_engine(settings.postgres_dsn, pool_pre_ping=True),
        redis=Redis.from_url(settings.redis_url, decode_responses=True),
        http=http,
        llm=ResilientLLMProvider(LMStudioProvider(settings), service_name=settings.service_name),
        qdrant_client=qdrant_client,
        auth=create_auth_provider(settings),
    )


def dependencies_from_request(request: Request) -> Dependencies:
    """Return the process-owned dependency container; never allocate per request."""
    return cast("Dependencies", request.app.state.dependencies)


async def get_session(request: Request) -> AsyncGenerator[AsyncSession, None]:
    dependencies = dependencies_from_request(request)
    with span("database.session", **{"db.system": "postgresql"}):
        async with AsyncSession(dependencies.engine, expire_on_commit=False) as session:
            yield session


__all__ = [
    "Dependencies",
    "ProbeResult",
    "ProviderError",
    "RedisRateLimiter",
    "dependencies_from_request",
    "get_dependencies",
    "get_session",
    "run_probe",
]
