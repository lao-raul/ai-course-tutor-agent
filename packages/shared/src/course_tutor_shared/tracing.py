"""OpenTelemetry setup and safe manual spans.

Tracing is opt-in. When enabled, spans are exported over OTLP/HTTP and carry only
operational attributes; prompts, source text, memory values and credentials are never
attached. The same helpers work as no-ops when tracing is disabled.
"""

from __future__ import annotations

from collections.abc import Iterator, MutableMapping
from contextlib import contextmanager
from typing import Any

from course_tutor_shared.config import Settings, get_settings
from course_tutor_shared.correlation import CORRELATION_ID_HEADER, get_correlation_id
from course_tutor_shared.logging import get_logger

_tracer: Any | None = None
_provider: Any | None = None


def configure_tracing(settings: Settings | None = None) -> None:
    """Configure one process-wide OTLP tracer provider when explicitly enabled."""
    global _provider, _tracer
    settings = settings or get_settings()

    if not settings.otel_enabled:
        _tracer = None
        return

    if _provider is not None:
        _tracer = _provider.get_tracer(settings.service_name)
        return

    try:
        from opentelemetry import trace
        from opentelemetry.exporter.otlp.proto.http.trace_exporter import OTLPSpanExporter
        from opentelemetry.sdk.resources import Resource
        from opentelemetry.sdk.trace import TracerProvider
        from opentelemetry.sdk.trace.export import BatchSpanProcessor
    except ImportError:
        get_logger(__name__).warning("otel_enabled_but_sdk_missing")
        _tracer = None
        return

    provider = TracerProvider(
        resource=Resource.create(
            {
                "service.name": settings.service_name,
                "service.version": settings.build_version,
                "service.instance.id": settings.build_revision,
                "deployment.environment.name": settings.environment.value,
            }
        )
    )
    if settings.otel_exporter_otlp_endpoint:
        exporter = OTLPSpanExporter(endpoint=settings.otel_exporter_otlp_endpoint)
        provider.add_span_processor(BatchSpanProcessor(exporter))
    else:
        get_logger(__name__).warning("otel_exporter_endpoint_missing", exporter="none")
    trace.set_tracer_provider(provider)
    _provider = provider
    _tracer = provider.get_tracer(settings.service_name)


@contextmanager
def span(name: str, **attributes: Any) -> Iterator[Any]:
    """Start a span if tracing is configured, otherwise do nothing."""
    if _tracer is None:
        yield None
        return

    correlation_id = get_correlation_id()
    with _tracer.start_as_current_span(name) as active_span:
        if correlation_id:
            active_span.set_attribute("course_tutor.correlation_id", correlation_id)
        for key, value in attributes.items():
            if value is not None:
                active_span.set_attribute(key, value)
        yield active_span


def outbound_trace_headers() -> dict[str, str]:
    """Return W3C trace context plus the operational correlation ID."""
    headers: MutableMapping[str, str] = {}
    try:
        from opentelemetry.propagate import inject

        inject(headers)
    except ImportError:
        pass
    if correlation_id := get_correlation_id():
        headers[CORRELATION_ID_HEADER] = correlation_id
    return dict(headers)


@contextmanager
def server_span(name: str, headers: dict[str, str], **attributes: Any) -> Iterator[Any]:
    """Continue an inbound W3C trace without recording request payloads."""
    if _tracer is None:
        yield None
        return
    from opentelemetry.propagate import extract
    from opentelemetry.trace import SpanKind

    context = extract(headers)
    with _tracer.start_as_current_span(name, context=context, kind=SpanKind.SERVER) as active_span:
        if correlation_id := get_correlation_id():
            active_span.set_attribute("course_tutor.correlation_id", correlation_id)
        for key, value in attributes.items():
            if value is not None:
                active_span.set_attribute(key, value)
        yield active_span
