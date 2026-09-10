"""Application factory."""

from __future__ import annotations

from collections.abc import AsyncIterator
from contextlib import asynccontextmanager

from fastapi import FastAPI

from course_tutor_api.dependencies import get_dependencies
from course_tutor_api.local_bootstrap import ensure_local_identity
from course_tutor_api.routes import admin, chat, courses, health
from course_tutor_shared import (
    CorrelationIdMiddleware,
    Settings,
    configure_logging,
    configure_tracing,
    get_logger,
    get_settings,
)

logger = get_logger(__name__)


def create_app(settings: Settings | None = None) -> FastAPI:
    settings = settings or get_settings()
    configure_logging(settings)
    configure_tracing(settings)

    @asynccontextmanager
    async def lifespan(app: FastAPI) -> AsyncIterator[None]:
        dependencies = get_dependencies(settings)
        app.state.settings = settings
        app.state.dependencies = dependencies
        try:
            await ensure_local_identity(dependencies.engine, settings)
            logger.info(
                "api_starting",
                environment=settings.environment.value,
                chat_model=settings.llm_chat_model,
                embedding_model=settings.llm_embedding_model,
                embedding_dimension=settings.llm_embedding_dimension,
            )
            yield
        finally:
            await dependencies.aclose()
            logger.info("api_stopped")

    app = FastAPI(
        title="AI Course Tutor Agent API",
        version="0.1.0",
        description="Gateway/BFF for the course teaching assistant.",
        lifespan=lifespan,
    )
    app.add_middleware(CorrelationIdMiddleware)
    app.include_router(health.router)
    app.include_router(admin.router)
    app.include_router(chat.router)
    app.include_router(courses.router)
    return app
