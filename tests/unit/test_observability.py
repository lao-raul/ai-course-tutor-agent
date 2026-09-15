"""Bounded operational telemetry and dependency attribution."""

from __future__ import annotations

import httpx
from httpx import AsyncClient

from course_tutor_api.dependencies import MinioProbe, run_probe
from course_tutor_shared import correlation_id_var, outbound_trace_headers


async def test_metrics_endpoint_has_bounded_route_labels(api_client: AsyncClient) -> None:
    correlation_id = "must-not-be-a-metric-label"
    await api_client.get("/healthz", headers={"X-Correlation-ID": correlation_id})
    response = await api_client.get("/metrics")

    assert response.status_code == 200
    assert "course_tutor_http_requests_total" in response.text
    assert 'route="/healthz"' in response.text
    assert correlation_id not in response.text


async def test_minio_readiness_probe_is_bounded_and_attributed() -> None:
    def handler(request: httpx.Request) -> httpx.Response:
        assert request.url.path == "/minio/health/ready"
        return httpx.Response(503, text="not ready")

    async with httpx.AsyncClient(transport=httpx.MockTransport(handler)) as client:
        result = await run_probe(MinioProbe(client, "http://minio.invalid"))

    assert result.name == "minio"
    assert result.healthy is False
    assert "503" in (result.detail or "")


def test_outbound_calls_propagate_correlation_without_payload() -> None:
    token = correlation_id_var.set("traceable-request")
    try:
        headers = outbound_trace_headers()
    finally:
        correlation_id_var.reset(token)

    assert headers["X-Correlation-ID"] == "traceable-request"
    assert set(headers).issubset({"X-Correlation-ID", "traceparent", "tracestate", "baggage"})
