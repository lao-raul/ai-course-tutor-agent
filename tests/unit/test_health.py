"""Liveness and readiness behaviour.

Acceptance criterion 6 requires a dependency outage to surface as a user-safe error
with a traceable signal — not a hung request and not a generic 503.
"""

from __future__ import annotations

import asyncio

import pytest
from httpx import AsyncClient

from course_tutor_api.dependencies import PROBE_TIMEOUT_SECONDS, run_probe
from course_tutor_api.providers import FakeLLMProvider, ProviderError
from course_tutor_shared.correlation import CORRELATION_ID_HEADER
from tests.conftest import StubProbe


async def test_liveness_does_not_touch_dependencies(api_client: AsyncClient) -> None:
    response = await api_client.get("/healthz")
    assert response.status_code == 200
    assert response.json() == {
        "status": "ok",
        "service": "course-tutor-test",
        "version": "0.1.0",
    }


async def test_readiness_reports_every_component(api_client: AsyncClient) -> None:
    response = await api_client.get("/readyz")
    assert response.status_code == 200
    body = response.json()
    assert body["status"] == "ready"
    assert {c["name"] for c in body["components"]} == {
        "postgres",
        "redis",
        "qdrant",
        "llm",
    }
    assert all(c["healthy"] for c in body["components"])


async def test_readiness_degrades_and_attributes_the_failure(
    api_client: AsyncClient, fake_llm: FakeLLMProvider
) -> None:
    """A simulated LM Studio outage must name the failing component, not just 503."""
    fake_llm.healthy = False

    response = await api_client.get("/readyz")

    assert response.status_code == 503
    body = response.json()
    assert body["status"] == "degraded"
    llm = next(c for c in body["components"] if c["name"] == "llm")
    assert llm["healthy"] is False
    assert "unhealthy" in llm["detail"]
    # The other stores are still reported healthy, so the outage is attributable.
    assert all(c["healthy"] for c in body["components"] if c["name"] != "llm")


async def test_correlation_id_is_echoed_when_supplied(api_client: AsyncClient) -> None:
    response = await api_client.get("/healthz", headers={CORRELATION_ID_HEADER: "abc123"})
    assert response.headers[CORRELATION_ID_HEADER] == "abc123"


async def test_correlation_id_is_minted_when_absent(api_client: AsyncClient) -> None:
    response = await api_client.get("/healthz")
    assert response.headers.get(CORRELATION_ID_HEADER)


async def test_probe_failure_is_captured_not_raised() -> None:
    result = await run_probe(StubProbe("postgres", error=ProviderError("connection refused")))
    assert result.healthy is False
    assert result.detail == "connection refused"
    assert result.name == "postgres"


async def test_probe_timeout_is_bounded() -> None:
    """A hung dependency must not hang readiness."""

    class HangingProbe:
        name = "qdrant"

        async def check(self) -> None:
            await asyncio.sleep(PROBE_TIMEOUT_SECONDS + 10)

    with pytest.MonkeyPatch.context() as patch:
        patch.setattr("course_tutor_api.dependencies.PROBE_TIMEOUT_SECONDS", 0.05)
        result = await run_probe(HangingProbe())

    assert result.healthy is False
    assert "timed out" in (result.detail or "")


async def test_healthy_probe_records_latency() -> None:
    result = await run_probe(StubProbe("redis"))
    assert result.healthy is True
    assert result.latency_ms >= 0
    assert result.detail is None
