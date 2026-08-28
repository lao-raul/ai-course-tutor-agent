"""Structured logging.

Logs carry the correlation ID on every record and never contain prompt or source
content (function-spec §5, Observability/Privacy).
"""

from __future__ import annotations

import logging
import sys
from collections.abc import MutableMapping
from typing import Any, cast

import structlog

from course_tutor_shared.config import LogFormat, Settings, get_settings
from course_tutor_shared.correlation import get_correlation_id

_configured = False


def _inject_correlation_id(
    _logger: Any, _method: str, event_dict: MutableMapping[str, Any]
) -> MutableMapping[str, Any]:
    correlation_id = get_correlation_id()
    if correlation_id is not None:
        event_dict.setdefault("correlation_id", correlation_id)
    return event_dict


def configure_logging(settings: Settings | None = None, *, force: bool = False) -> None:
    """Idempotently configure structlog and the stdlib root logger."""
    global _configured
    if _configured and not force:
        return

    settings = settings or get_settings()

    logging.basicConfig(
        format="%(message)s",
        stream=sys.stdout,
        level=getattr(logging, settings.log_level),
        force=True,
    )

    renderer: structlog.typing.Processor = (
        structlog.processors.JSONRenderer()
        if settings.log_format is LogFormat.JSON
        else structlog.dev.ConsoleRenderer()
    )

    structlog.configure(
        processors=[
            structlog.contextvars.merge_contextvars,
            structlog.processors.add_log_level,
            structlog.processors.TimeStamper(fmt="iso", utc=True),
            _inject_correlation_id,
            structlog.processors.StackInfoRenderer(),
            structlog.processors.format_exc_info,
            renderer,
        ],
        wrapper_class=structlog.make_filtering_bound_logger(getattr(logging, settings.log_level)),
        logger_factory=structlog.stdlib.LoggerFactory(),
        cache_logger_on_first_use=True,
    )

    _configured = True


def get_logger(name: str | None = None) -> structlog.stdlib.BoundLogger:
    """Return a bound logger, configuring logging on first use."""
    configure_logging()
    return cast("structlog.stdlib.BoundLogger", structlog.get_logger(name))
