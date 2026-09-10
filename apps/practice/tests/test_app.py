from __future__ import annotations

import json
from pathlib import Path
from typing import Any, cast
from uuid import UUID, uuid4

from fastapi.testclient import TestClient

from course_tutor_auth import Principal
from course_tutor_contracts.enums import AccessLabel, UserRole
from course_tutor_practice.app import PracticeDependencies, create_app
from course_tutor_shared import Settings
from course_tutor_shared.config import Environment


def _client() -> TestClient:
    settings = Settings(environment=Environment.TEST, service_name="practice-api-test")
    return TestClient(create_app(settings))


def test_health_and_readiness_are_public_and_stable() -> None:
    client = _client()
    assert client.get("/healthz").json() == {
        "status": "ok",
        "service": "practice-api",
        "version": "0.1.0-dev",
        "revision": "unknown",
    }
    assert client.get("/readyz").json() == {"status": "ready"}


def test_capabilities_require_auth_and_report_generation_unavailable() -> None:
    client = _client()
    assert client.get("/v1/practice/capabilities").status_code == 401
    response = client.get(
        "/v1/practice/capabilities",
        headers={"Authorization": "Bearer local-dev-token"},
    )
    assert response.status_code == 200
    assert response.json() == {
        "exercise_generation": "not_implemented",
        "implemented_features": [],
    }


def test_generation_returns_deterministic_501_with_correlation_id() -> None:
    client = _client()
    course_id = uuid4()
    response = client.post(
        f"/v1/practice/courses/{course_id}/exercises:generate",
        headers={
            "Authorization": "Bearer local-dev-token",
            "X-Correlation-ID": "practice-test-correlation",
        },
        json={"count": 3, "topic": "Bayes", "difficulty": "introductory"},
    )
    assert response.status_code == 501
    assert response.json() == {
        "code": "practice_generation_not_implemented",
        "message": "Practice exercise generation is not implemented in v0.2.",
        "correlation_id": "practice-test-correlation",
    }


class _StudentProvider:
    def __init__(self, course_ids: frozenset[UUID]) -> None:
        self._course_ids = course_ids

    async def authenticate(self, _token: str) -> Principal:
        return Principal(
            user_id=uuid4(),
            tenant_id=uuid4(),
            role=UserRole.STUDENT,
            access_label=AccessLabel.ENROLLED,
            subject="student",
            course_ids=self._course_ids,
        )


def test_generation_fails_closed_for_course_outside_verified_scope() -> None:
    client = _client()
    cast(Any, client.app).state.dependencies = PracticeDependencies(
        auth=_StudentProvider(frozenset())
    )
    response = client.post(
        f"/v1/practice/courses/{uuid4()}/exercises:generate",
        headers={"Authorization": "Bearer token"},
        json={},
    )
    assert response.status_code == 403


def test_openapi_has_no_settings_or_secret_schema() -> None:
    schema = _client().get("/openapi.json").json()
    rendered = str(schema).lower()
    assert "settings" not in schema["components"]["schemas"]
    assert "secretstr" not in rendered
    assert {
        operation["operationId"]
        for path in schema["paths"].values()
        for method, operation in path.items()
        if method in {"get", "post"}
    } == {
        "practiceHealth",
        "practiceReady",
        "getPracticeCapabilities",
        "generatePracticeExercises",
    }

    canonical_path = (
        Path(__file__).resolve().parents[3] / "packages/contracts/openapi/practice-api.v1.json"
    )
    canonical = json.loads(canonical_path.read_text(encoding="utf-8"))
    canonical_operations = {
        operation["operationId"]
        for path in canonical["paths"].values()
        for method, operation in path.items()
        if method in {"get", "post"}
    }
    assert canonical_operations == {
        operation["operationId"]
        for path in schema["paths"].values()
        for method, operation in path.items()
        if method in {"get", "post"}
    }
