from __future__ import annotations

import json
from pathlib import Path
from typing import Any, cast
from uuid import UUID, uuid4

from fastapi.testclient import TestClient

from course_tutor_auth import Principal
from course_tutor_contracts import (
    BookLifecycleStatus,
    CatalogBookDetail,
    CatalogBookPage,
    CatalogBookSummary,
    CatalogCategoryView,
    CatalogCourseView,
    CategoryType,
    EducationLevel,
)
from course_tutor_contracts.enums import AccessLabel, UserRole
from course_tutor_practice.adapters.memory_repository import InMemoryPracticeRepository
from course_tutor_practice.app import PracticeDependencies, create_app
from course_tutor_shared import Settings
from course_tutor_shared.config import Environment

AUTHORIZATION = f"Bearer {Settings().local_auth_token.get_secret_value()}"


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


def test_capabilities_require_auth_and_report_async_generation() -> None:
    client = _client()
    assert client.get("/v1/practice/capabilities").status_code == 401
    response = client.get(
        "/v1/practice/capabilities",
        headers={"Authorization": AUTHORIZATION},
    )
    assert response.status_code == 200
    assert response.json() == {
        "exercise_generation": "asynchronous_jobs",
        "implemented_features": [
            "default_study_plan",
            "generation_jobs",
            "practice_sets",
            "attempts",
            "study_progress",
            "resume",
        ],
    }


def test_deprecated_generation_requires_initialized_book_plan() -> None:
    client = _client()
    course_id = uuid4()
    response = client.post(
        f"/v1/practice/courses/{course_id}/exercises:generate",
        headers={
            "Authorization": AUTHORIZATION,
            "X-Correlation-ID": "practice-test-correlation",
            "Idempotency-Key": "legacy-without-plan",
        },
        json={"count": 3, "topic": "Bayes", "difficulty": "introductory"},
    )
    assert response.status_code == 409
    assert "initialize the book StudyPlan" in response.json()["detail"]


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
        auth=_StudentProvider(frozenset()),
        repository=InMemoryPracticeRepository(),
    )
    response = client.post(
        f"/v1/practice/courses/{uuid4()}/exercises:generate",
        headers={"Authorization": "Bearer token", "Idempotency-Key": "denied"},
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
        if method in {"get", "post", "put", "delete"}
    } == {
        "practiceHealth",
        "practiceReady",
        "getPracticeCapabilities",
        "getBookStudyPlan",
        "createPracticeGeneration",
        "getPracticeGeneration",
        "cancelPracticeGeneration",
        "getPracticeSet",
        "generatePracticeExercises",
        "getPracticeBook",
        "listBookCourses",
        "listPracticeCategories",
        "searchPracticeBooks",
        "submitPracticeAnswer",
        "giveUpPracticeExercise",
        "getStudyStatus",
        "resumeStudy",
        "getStudyMemorySignals",
        "reportPracticeExercise",
        "resetResumeCursor",
        "setStudyMemoryConsent",
    }

    canonical_path = (
        Path(__file__).resolve().parents[3] / "packages/contracts/openapi/practice-api.v1.json"
    )
    canonical = json.loads(canonical_path.read_text(encoding="utf-8"))
    canonical_operations = {
        operation["operationId"]
        for path in canonical["paths"].values()
        for method, operation in path.items()
        if method in {"get", "post", "put", "delete"}
    }
    assert canonical_operations == {
        operation["operationId"]
        for path in schema["paths"].values()
        for method, operation in path.items()
        if method in {"get", "post", "put", "delete"}
    }


class _CatalogStub:
    def __init__(self) -> None:
        self.book_id = uuid4()
        self.course_id = uuid4()
        self.run_id = uuid4()
        self.version_id = uuid4()
        self.last_bearer: str | None = None
        self.last_params: dict[str, object] = {}

    def _book(self) -> CatalogBookSummary:
        return CatalogBookSummary(
            id=self.book_id,
            title="义务教育教科书·英语三年级上册",
            education_level=EducationLevel.PRIMARY,
            subject="英语",
            grade="3",
            publisher="外研社",
            series="外研社版（三年级起点）（主编：陈琳）",  # noqa: RUF001
            edition="外研社版",
            start_grade="3",
            editor="陈琳",
            term="上册",
            language="en",
            lifecycle_status=BookLifecycleStatus.PUBLISHED,
        )

    async def list_categories(
        self, bearer: str, _correlation_id: str | None
    ) -> list[CatalogCategoryView]:
        self.last_bearer = bearer
        return [
            CatalogCategoryView(
                id=uuid4(),
                stable_key="education:primary",
                display_name="小学",
                category_type=CategoryType.EDUCATION_LEVEL,
                book_count=1,
            )
        ]

    async def search_books(
        self,
        bearer: str,
        _correlation_id: str | None,
        params: dict[str, object],
    ) -> CatalogBookPage:
        self.last_bearer = bearer
        self.last_params = params
        return CatalogBookPage(items=(self._book(),))

    async def get_book(
        self, _book_id: UUID, bearer: str, _correlation_id: str | None
    ) -> CatalogBookDetail:
        self.last_bearer = bearer
        return CatalogBookDetail(
            **self._book().model_dump(),
            courses=tuple(await self.list_book_courses(self.book_id, bearer, None)),
        )

    async def list_book_courses(
        self, _book_id: UUID, bearer: str, _correlation_id: str | None
    ) -> list[CatalogCourseView]:
        self.last_bearer = bearer
        return [
            CatalogCourseView(
                course_id=self.course_id,
                course_run_id=self.run_id,
                code="TXT-TEST",
                name="英语三年级上册",
                content_version_id=self.version_id,
            )
        ]


def test_catalog_facade_forwards_identity_and_filters_without_nas_paths() -> None:
    settings = Settings(environment=Environment.TEST, service_name="practice-api-test")
    app = create_app(settings)
    current = cast(Any, app).state.dependencies
    catalog = _CatalogStub()
    cast(Any, app).state.dependencies = PracticeDependencies(
        auth=current.auth,
        catalog=catalog,
    )
    client = TestClient(app)
    response = client.get(
        "/v1/practice/catalog/books",
        headers={"Authorization": AUTHORIZATION},
        params={"education_level": "primary", "publisher": "外研社"},
    )
    assert response.status_code == 200
    assert response.json()["items"][0]["publisher"] == "外研社"
    assert catalog.last_bearer == AUTHORIZATION
    assert catalog.last_params["education_level"] == "primary"
    assert "/Volumes/" not in response.text
