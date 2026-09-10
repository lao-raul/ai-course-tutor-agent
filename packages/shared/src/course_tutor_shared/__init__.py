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
from course_tutor_shared.pipeline import PIPELINE_VERSION
from course_tutor_shared.tracing import configure_tracing, span

__all__ = [
    "PIPELINE_VERSION",
    "AuthMode",
    "CorrelationIdMiddleware",
    "Environment",
    "Settings",
    "configure_logging",
    "configure_tracing",
    "correlation_id_var",
    "get_correlation_id",
    "get_logger",
    "get_settings",
    "new_correlation_id",
    "span",
]
