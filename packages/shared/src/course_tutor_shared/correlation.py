"""Correlation IDs.

One ID follows a request across the gateway, orchestrator, retrieval, memory and the
model gateway, so a single trace can be reconstructed from logs alone.
"""

from __future__ import annotations

import uuid
from collections.abc import Awaitable, Callable
from contextvars import ContextVar

from starlette.requests import Request
from starlette.responses import Response
from starlette.types import ASGIApp

CORRELATION_ID_HEADER = "X-Correlation-ID"

correlation_id_var: ContextVar[str | None] = ContextVar("correlation_id", default=None)


def new_correlation_id() -> str:
    return uuid.uuid4().hex


def get_correlation_id() -> str | None:
    return correlation_id_var.get()


class CorrelationIdMiddleware:
    """Adopt an inbound correlation ID or mint one, and echo it on the response.

    Implemented against Starlette's ``BaseHTTPMiddleware``-free surface so the package
    keeps no FastAPI dependency.
    """

    def __init__(self, app: ASGIApp) -> None:
        self.app = app

    async def __call__(self, scope, receive, send) -> None:  # type: ignore[no-untyped-def]
        if scope["type"] != "http":
            await self.app(scope, receive, send)
            return

        request = Request(scope)
        incoming = request.headers.get(CORRELATION_ID_HEADER)
        correlation_id = incoming or new_correlation_id()
        token = correlation_id_var.set(correlation_id)

        async def send_with_header(message):  # type: ignore[no-untyped-def]
            if message["type"] == "http.response.start":
                headers = message.setdefault("headers", [])
                headers.append((CORRELATION_ID_HEADER.lower().encode(), correlation_id.encode()))
            await send(message)

        try:
            await self.app(scope, receive, send_with_header)
        finally:
            correlation_id_var.reset(token)


async def bind_correlation_id(
    request: Request, call_next: Callable[[Request], Awaitable[Response]]
) -> Response:
    """Functional variant for stacks that prefer ``BaseHTTPMiddleware``."""
    incoming = request.headers.get(CORRELATION_ID_HEADER)
    correlation_id = incoming or new_correlation_id()
    token = correlation_id_var.set(correlation_id)
    try:
        response = await call_next(request)
        response.headers[CORRELATION_ID_HEADER] = correlation_id
        return response
    finally:
        correlation_id_var.reset(token)
