"""OpenTelemetry stub.

Phase 0 ships the call sites, not the exporter. ``span()`` is a no-op context manager
until ``OTEL_ENABLED`` is set and the OTel SDK is installed (Phase 4), so instrumenting
code now costs nothing and needs no rewrite later.
"""

from __future__ import annotations

from collections.abc import Iterator
from contextlib import contextmanager
from typing import Any

from course_tutor_shared.config import Settings, get_settings
from course_tutor_shared.logging import get_logger

_tracer: Any | None = None


def configure_tracing(settings: Settings | None = None) -> None:
    """Install a real tracer when tracing is enabled and the SDK is available."""
    global _tracer
    settings = settings or get_settings()

    if not settings.otel_enabled:
        _tracer = None
        return

    try:
        from opentelemetry import trace
    except ImportError:
        get_logger(__name__).warning(
            "otel_enabled_but_sdk_missing",
            hint="install opentelemetry-sdk to export traces; falling back to no-op",
        )
        _tracer = None
        return

    _tracer = trace.get_tracer(settings.service_name)


@contextmanager
def span(name: str, **attributes: Any) -> Iterator[Any]:
    """Start a span if tracing is configured, otherwise do nothing."""
    if _tracer is None:
        yield None
        return

    with _tracer.start_as_current_span(name) as active_span:
        for key, value in attributes.items():
            active_span.set_attribute(key, value)
        yield active_span
