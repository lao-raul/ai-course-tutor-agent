"""Liveness and readiness.

``/healthz`` answers "is this process alive" and must never touch a dependency.
``/readyz`` answers "can it serve traffic" and reports every backing store by name.
"""

from __future__ import annotations

from typing import Literal

from fastapi import APIRouter, Request, Response, status
from pydantic import BaseModel

from course_tutor_api.dependencies import Dependencies

router = APIRouter(tags=["health"])


class LivenessResponse(BaseModel):
    status: Literal["ok"]
    service: str
    version: str


class ComponentHealth(BaseModel):
    name: str
    healthy: bool
    latency_ms: float
    detail: str | None = None


class ReadinessResponse(BaseModel):
    status: Literal["ready", "degraded"]
    components: list[ComponentHealth]


@router.get("/healthz", response_model=LivenessResponse)
async def liveness(request: Request) -> LivenessResponse:
    return LivenessResponse(
        status="ok",
        service=request.app.state.settings.service_name,
        version=request.app.version,
    )


@router.get("/readyz", response_model=ReadinessResponse)
async def readiness(request: Request, response: Response) -> ReadinessResponse:
    dependencies: Dependencies = request.app.state.dependencies
    results = await dependencies.readiness()
    components = [
        ComponentHealth(
            name=result.name,
            healthy=result.healthy,
            latency_ms=round(result.latency_ms, 2),
            detail=result.detail,
        )
        for result in results
    ]
    ready = all(component.healthy for component in components)
    if not ready:
        response.status_code = status.HTTP_503_SERVICE_UNAVAILABLE
    return ReadinessResponse(status="ready" if ready else "degraded", components=components)
