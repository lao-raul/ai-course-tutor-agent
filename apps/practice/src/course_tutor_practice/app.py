"""Application factory for the reserved Practice API boundary."""

from __future__ import annotations

from dataclasses import dataclass
from typing import Annotated, Literal
from uuid import UUID

from fastapi import Depends, FastAPI, HTTPException, Response, status
from fastapi.responses import JSONResponse
from pydantic import BaseModel

from course_tutor_auth import (
    AuthProvider,
    Principal,
    create_auth_provider,
    get_current_principal,
    principal_can_access_course,
)
from course_tutor_contracts import (
    GeneratePracticeRequest,
    PracticeCapabilities,
    PracticeNotImplementedError,
)
from course_tutor_practice import __version__
from course_tutor_shared import (
    CorrelationIdMiddleware,
    PrometheusMiddleware,
    Settings,
    configure_logging,
    configure_tracing,
    get_correlation_id,
    get_settings,
    metrics_endpoint,
)


@dataclass(frozen=True, slots=True)
class PracticeDependencies:
    auth: AuthProvider


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

    app = FastAPI(
        title="Course Tutor Practice API",
        version=__version__,
        description=(
            "Reserved API boundary for future exercise generation. Generation is "
            "intentionally unavailable in v0.2."
        ),
    )
    app.state.settings = settings
    app.state.dependencies = PracticeDependencies(auth=create_auth_provider(settings))
    app.add_middleware(CorrelationIdMiddleware)
    if settings.metrics_enabled:
        app.add_middleware(PrometheusMiddleware, service_name=settings.service_name)
        app.add_api_route("/metrics", metrics_endpoint, methods=["GET"], include_in_schema=False)

    @app.get("/healthz", response_model=HealthResponse, operation_id="practiceHealth")
    async def health() -> HealthResponse:
        return HealthResponse(
            version=settings.build_version,
            revision=settings.build_revision,
        )

    @app.get("/readyz", response_model=ReadinessResponse, operation_id="practiceReady")
    async def ready(response: Response) -> ReadinessResponse:
        # The dummy service has no network or storage dependency. Successful startup
        # means configuration and the auth adapter were constructed successfully.
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

    @app.post(
        "/v1/practice/courses/{course_id}/exercises:generate",
        operation_id="generatePracticeExercises",
        responses={status.HTTP_501_NOT_IMPLEMENTED: {"model": PracticeNotImplementedError}},
    )
    async def generate(
        course_id: UUID,
        _body: GeneratePracticeRequest,
        principal: Annotated[Principal, Depends(get_current_principal)],
    ) -> JSONResponse:
        if not principal_can_access_course(principal, course_id):
            raise HTTPException(
                status_code=status.HTTP_403_FORBIDDEN,
                detail="course is outside the authenticated scope",
            )
        error = PracticeNotImplementedError(
            message="Practice exercise generation is not implemented in v0.2.",
            correlation_id=get_correlation_id() or "unavailable",
        )
        return JSONResponse(
            status_code=status.HTTP_501_NOT_IMPLEMENTED,
            content=error.model_dump(mode="json"),
        )

    return app
