"""Dependency container and health probes.

Readiness reports each backing store separately so an outage is attributable rather
than a generic 503 (function-spec acceptance criterion 6).
"""

from __future__ import annotations

import asyncio
import time
from dataclasses import dataclass, field
from typing import Protocol

import httpx
from redis.asyncio import Redis
from sqlalchemy.ext.asyncio import AsyncEngine, create_async_engine
from sqlalchemy.sql import text

from course_tutor_api.providers import LLMProvider, LMStudioProvider, ProviderError
from course_tutor_shared import Settings, get_logger, get_settings

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
    _probes: list[Probe] = field(default_factory=list)

    def probes(self) -> list[Probe]:
        if not self._probes:
            self._probes = [
                PostgresProbe(self.engine),
                RedisProbe(self.redis),
                QdrantProbe(self.http, self.settings.qdrant_url),
                LLMProbe(self.llm),
            ]
        return self._probes

    async def readiness(self) -> list[ProbeResult]:
        return list(await asyncio.gather(*(run_probe(p) for p in self.probes())))

    async def aclose(self) -> None:
        await self.redis.aclose()
        await self.http.aclose()
        await self.engine.dispose()
        if (close := getattr(self.llm, "aclose", None)) is not None:
            await close()


def get_dependencies(settings: Settings | None = None) -> Dependencies:
    settings = settings or get_settings()
    http = httpx.AsyncClient(timeout=httpx.Timeout(PROBE_TIMEOUT_SECONDS))
    return Dependencies(
        settings=settings,
        engine=create_async_engine(settings.postgres_dsn, pool_pre_ping=True),
        redis=Redis.from_url(settings.redis_url, decode_responses=True),
        http=http,
        llm=LMStudioProvider(settings),
    )


__all__ = [
    "Dependencies",
    "ProbeResult",
    "ProviderError",
    "get_dependencies",
    "run_probe",
]
