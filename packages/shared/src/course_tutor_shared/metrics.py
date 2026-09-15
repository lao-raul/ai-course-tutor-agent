"""Prometheus metrics with deliberately bounded labels.

No metric contains tenant, user, course, prompt, source path or correlation ID. Those
values belong in access-controlled traces/audit records, not time-series labels.
"""

from __future__ import annotations

import time
from typing import Any

from prometheus_client import CONTENT_TYPE_LATEST, Counter, Gauge, Histogram, generate_latest
from starlette.requests import Request
from starlette.responses import Response
from starlette.types import ASGIApp

HTTP_REQUESTS = Counter(
    "course_tutor_http_requests_total",
    "Completed HTTP requests.",
    ("service", "method", "route", "status_class"),
)
HTTP_DURATION = Histogram(
    "course_tutor_http_request_duration_seconds",
    "HTTP request duration.",
    ("service", "method", "route"),
    buckets=(0.01, 0.025, 0.05, 0.1, 0.25, 0.5, 1, 2.5, 5, 10, 30, 120),
)
CHAT_TTFT = Histogram(
    "course_tutor_chat_time_to_first_event_seconds",
    "Time from accepted chat request to the first user-visible SSE event.",
    ("service", "outcome"),
    buckets=(0.1, 0.25, 0.5, 1, 2, 3, 5, 8, 15, 30, 60, 120),
)
DEPENDENCY_UP = Gauge(
    "course_tutor_dependency_up",
    "Whether the most recent readiness probe succeeded.",
    ("service", "dependency"),
)
DEPENDENCY_DURATION = Histogram(
    "course_tutor_dependency_probe_duration_seconds",
    "Dependency readiness probe duration.",
    ("service", "dependency"),
    buckets=(0.005, 0.01, 0.025, 0.05, 0.1, 0.25, 0.5, 1, 2.5, 5),
)
LLM_REQUESTS = Counter(
    "course_tutor_llm_requests_total",
    "Inference requests by operation and bounded outcome.",
    ("service", "operation", "outcome"),
)
LLM_DURATION = Histogram(
    "course_tutor_llm_request_duration_seconds",
    "Inference request duration.",
    ("service", "operation"),
    buckets=(0.05, 0.1, 0.25, 0.5, 1, 2.5, 5, 10, 30, 60, 120),
)
LLM_CIRCUIT_OPEN = Gauge(
    "course_tutor_llm_circuit_open",
    "Whether the inference circuit breaker is open.",
    ("service",),
)
RETRIEVAL_REQUESTS = Counter(
    "course_tutor_retrieval_requests_total",
    "Retrieval requests by bounded outcome.",
    ("service", "outcome"),
)
RETRIEVAL_DURATION = Histogram(
    "course_tutor_retrieval_duration_seconds",
    "Retrieval and reranking duration.",
    ("service",),
    buckets=(0.01, 0.025, 0.05, 0.1, 0.25, 0.5, 1, 2.5, 5, 10),
)
INGESTION_JOBS = Counter(
    "course_tutor_ingestion_jobs_total",
    "Worker jobs by stable topic and outcome.",
    ("service", "topic", "outcome"),
)
OUTBOX_DEPTH = Gauge(
    "course_tutor_outbox_depth",
    "Current unprocessed outbox events by stable topic and state.",
    ("service", "topic", "state"),
)
MEMORY_OPERATIONS = Counter(
    "course_tutor_memory_operations_total",
    "Privacy-sensitive memory operations by action and outcome.",
    ("service", "action", "outcome"),
)
CONTENT_VERSION_OPERATIONS = Counter(
    "course_tutor_content_version_operations_total",
    "Content publication and rollback operations.",
    ("service", "action", "outcome"),
)


def _route_template(scope: dict[str, Any]) -> str:
    route = scope.get("route")
    path = getattr(route, "path", None)
    return str(path) if path else "unmatched"


class PrometheusMiddleware:
    """Record request rate/latency without using raw paths as labels."""

    def __init__(self, app: ASGIApp, *, service_name: str) -> None:
        self.app = app
        self.service_name = service_name

    async def __call__(self, scope, receive, send) -> None:  # type: ignore[no-untyped-def]
        if scope["type"] != "http" or scope.get("path") == "/metrics":
            await self.app(scope, receive, send)
            return

        started = time.perf_counter()
        status_code = 500

        async def send_with_status(message):  # type: ignore[no-untyped-def]
            nonlocal status_code
            if message["type"] == "http.response.start":
                status_code = int(message["status"])
            await send(message)

        try:
            await self.app(scope, receive, send_with_status)
        finally:
            route = _route_template(scope)
            method = str(scope.get("method", "UNKNOWN"))
            HTTP_REQUESTS.labels(self.service_name, method, route, f"{status_code // 100}xx").inc()
            HTTP_DURATION.labels(self.service_name, method, route).observe(
                time.perf_counter() - started
            )


async def metrics_endpoint(_request: Request) -> Response:
    return Response(generate_latest(), media_type=CONTENT_TYPE_LATEST)


def observe_dependency(service: str, dependency: str, healthy: bool, latency_ms: float) -> None:
    DEPENDENCY_UP.labels(service, dependency).set(1 if healthy else 0)
    DEPENDENCY_DURATION.labels(service, dependency).observe(latency_ms / 1000)


def observe_llm(service: str, operation: str, outcome: str, duration_seconds: float) -> None:
    LLM_REQUESTS.labels(service, operation, outcome).inc()
    LLM_DURATION.labels(service, operation).observe(duration_seconds)


def observe_retrieval(service: str, outcome: str, duration_seconds: float) -> None:
    RETRIEVAL_REQUESTS.labels(service, outcome).inc()
    RETRIEVAL_DURATION.labels(service).observe(duration_seconds)


def observe_chat_ttft(service: str, outcome: str, duration_seconds: float) -> None:
    CHAT_TTFT.labels(service, outcome).observe(duration_seconds)


def record_memory_operation(service: str, action: str, outcome: str = "success") -> None:
    MEMORY_OPERATIONS.labels(service, action, outcome).inc()


def record_content_version_operation(service: str, action: str, outcome: str = "success") -> None:
    CONTENT_VERSION_OPERATIONS.labels(service, action, outcome).inc()


def start_metrics_server(port: int) -> None:
    """Start the worker metrics HTTP endpoint.

    ``prometheus_client`` owns the daemon thread; returning ``None`` keeps the caller
    independent from its concrete server type.
    """
    from prometheus_client import start_http_server

    start_http_server(port)
