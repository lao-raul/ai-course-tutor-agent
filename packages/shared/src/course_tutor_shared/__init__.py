"""Cross-cutting concerns shared by every service: config, logging, IDs, tracing.

This package must stay dependency-light. It never imports service or app modules,
which keeps the extraction path in ADR-002 open.
"""

from course_tutor_shared.config import AuthMode, Environment, Settings, get_settings
from course_tutor_shared.correlation import (
    CorrelationIdMiddleware,
    correlation_id_var,
    get_correlation_id,
    new_correlation_id,
)
from course_tutor_shared.logging import configure_logging, get_logger
from course_tutor_shared.metrics import (
    CHAT_TTFT,
    INGESTION_JOBS,
    LLM_CIRCUIT_OPEN,
    OUTBOX_DEPTH,
    PrometheusMiddleware,
    metrics_endpoint,
    observe_chat_ttft,
    observe_dependency,
    observe_llm,
    observe_retrieval,
    record_content_version_operation,
    record_memory_operation,
    start_metrics_server,
)
from course_tutor_shared.pipeline import PIPELINE_VERSION
from course_tutor_shared.tracing import (
    configure_tracing,
    outbound_trace_headers,
    server_span,
    span,
)

__all__ = [
    "CHAT_TTFT",
    "INGESTION_JOBS",
    "LLM_CIRCUIT_OPEN",
    "OUTBOX_DEPTH",
    "PIPELINE_VERSION",
    "AuthMode",
    "CorrelationIdMiddleware",
    "Environment",
    "PrometheusMiddleware",
    "Settings",
    "configure_logging",
    "configure_tracing",
    "correlation_id_var",
    "get_correlation_id",
    "get_logger",
    "get_settings",
    "metrics_endpoint",
    "new_correlation_id",
    "observe_chat_ttft",
    "observe_dependency",
    "observe_llm",
    "observe_retrieval",
    "outbound_trace_headers",
    "record_content_version_operation",
    "record_memory_operation",
    "server_span",
    "span",
    "start_metrics_server",
]
