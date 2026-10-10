"""Application factory for the Hiruzen Practice API."""

from __future__ import annotations

from collections.abc import AsyncIterator
from contextlib import asynccontextmanager
from dataclasses import dataclass
from typing import Annotated, Literal

from fastapi import Depends, FastAPI, Response, status
from pydantic import BaseModel
from sqlalchemy.ext.asyncio import (
    AsyncEngine,
    AsyncSession,
    async_sessionmaker,
    create_async_engine,
)

from course_tutor_auth import AuthProvider, Principal, create_auth_provider, get_current_principal
from course_tutor_contracts import PracticeCapabilities
from course_tutor_practice import __version__
from course_tutor_practice.adapters.agent_client import AgentCatalogClient, HttpAgentCatalogClient
from course_tutor_practice.adapters.agent_outline import HttpAgentOutlineProvider
from course_tutor_practice.adapters.memory_repository import InMemoryPracticeRepository
from course_tutor_practice.adapters.rubric import OpenAICompatibleRubricEvaluator
from course_tutor_practice.application.evaluation import RubricEvaluator
from course_tutor_practice.ports import OutlineProvider, PracticeRepository
from course_tutor_practice.routes import attempts, catalog, generations, progress, reports
from course_tutor_shared import (
    CorrelationIdMiddleware,
    PrometheusMiddleware,
    Settings,
    configure_logging,
    configure_tracing,
    get_settings,
    metrics_endpoint,
)
from course_tutor_shared.config import Environment


@dataclass(frozen=True, slots=True)
class PracticeDependencies:
    auth: AuthProvider
    catalog: AgentCatalogClient | None = None
    outline: OutlineProvider | None = None
    repository: PracticeRepository | None = None
    session_factory: async_sessionmaker[AsyncSession] | None = None
    engine: AsyncEngine | None = None
    rubric_evaluator: RubricEvaluator | None = None


class HealthResponse(BaseModel, frozen=True):
    status: Literal["ok"] = "ok"
    service: Literal["practice-api"] = "practice-api"
    version: str
    revision: str


class ReadinessResponse(BaseModel, frozen=True):
    status: Literal["ready"] = "ready"


def create_app(settings: Settings | None = None) -> FastAPI:
    settings = settings or get_settings()
    configure_logging(settings)
    configure_tracing(settings)

    engine: AsyncEngine | None = None
    session_factory: async_sessionmaker[AsyncSession] | None = None
    repository: PracticeRepository | None = None
    if settings.environment is Environment.TEST:
        repository = InMemoryPracticeRepository()
    else:
        engine = create_async_engine(
            settings.practice_postgres_dsn or settings.postgres_dsn,
            pool_pre_ping=True,
        )
        session_factory = async_sessionmaker(engine, expire_on_commit=False)

    dependencies = PracticeDependencies(
        auth=create_auth_provider(settings),
        catalog=HttpAgentCatalogClient(settings.agent_base_url),
        outline=(
            None
            if settings.environment is Environment.TEST
            else HttpAgentOutlineProvider(settings.agent_base_url)
        ),
        repository=repository,
        session_factory=session_factory,
        engine=engine,
        rubric_evaluator=(
            None
            if settings.environment is Environment.TEST
            else OpenAICompatibleRubricEvaluator(
                settings.llm_base_url,
                settings.llm_chat_model,
                settings.llm_api_key.get_secret_value(),
            )
        ),
    )

    @asynccontextmanager
    async def lifespan(_app: FastAPI) -> AsyncIterator[None]:
        try:
            yield
        finally:
            for dependency in (
                dependencies.catalog,
                dependencies.outline,
                dependencies.rubric_evaluator,
            ):
                close = getattr(dependency, "aclose", None)
                if close is not None:
                    await close()
            if dependencies.engine is not None:
                await dependencies.engine.dispose()

    app = FastAPI(
        title="Course Tutor Practice API",
        version=__version__,
        description="Hiruzen practice generation, attempts, progress and safe resume.",
        lifespan=lifespan,
    )
    app.state.settings = settings
    app.state.dependencies = dependencies
    app.add_middleware(CorrelationIdMiddleware)
    if settings.metrics_enabled:
        app.add_middleware(PrometheusMiddleware, service_name=settings.service_name)
        app.add_api_route("/metrics", metrics_endpoint, methods=["GET"], include_in_schema=False)

    @app.get("/healthz", response_model=HealthResponse, operation_id="practiceHealth")
    async def health() -> HealthResponse:
        return HealthResponse(version=settings.build_version, revision=settings.build_revision)

    @app.get("/readyz", response_model=ReadinessResponse, operation_id="practiceReady")
    async def ready(response: Response) -> ReadinessResponse:
        response.status_code = status.HTTP_200_OK
        return ReadinessResponse()

    @app.get(
        "/v1/practice/capabilities",
        response_model=PracticeCapabilities,
        operation_id="getPracticeCapabilities",
    )
    async def capabilities(
        _principal: Annotated[Principal, Depends(get_current_principal)],
    ) -> PracticeCapabilities:
        return PracticeCapabilities()

    app.include_router(catalog.router)
    app.include_router(generations.router)
    app.include_router(attempts.router)
    app.include_router(progress.router)
    app.include_router(reports.router)
    return app
