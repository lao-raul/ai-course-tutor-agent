from __future__ import annotations

from datetime import UTC, datetime, timedelta
from typing import Any, cast
from uuid import UUID, uuid4

import pytest
from fastapi.testclient import TestClient

from course_tutor_auth import Principal
from course_tutor_contracts import (
    BookLifecycleStatus,
    CatalogBookDetail,
    CatalogBookOutline,
    CatalogCourseView,
    CatalogOutlineNode,
    ChoiceOption,
    EducationLevel,
    GeneratePracticeRequest,
    GenerationStatus,
    MultipleChoiceExerciseDraft,
    PracticeDifficulty,
    PracticeLanguage,
)
from course_tutor_contracts.enums import AccessLabel, UserRole
from course_tutor_practice.adapters.memory_repository import InMemoryPracticeRepository
from course_tutor_practice.app import PracticeDependencies, create_app
from course_tutor_practice.application.generation import GenerationService, StudyPlanService
from course_tutor_shared import Settings
from course_tutor_shared.config import Environment

AUTHORIZATION = f"Bearer {Settings().local_auth_token.get_secret_value()}"


class CatalogStub:
    def __init__(self) -> None:
        self.book_id = uuid4()
        self.course_id = uuid4()
        self.run_id = uuid4()
        self.version_id = uuid4()
        self.book = CatalogBookDetail(
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
        self.course = CatalogCourseView(
            course_id=self.course_id,
            course_run_id=self.run_id,
            code="TXT-EN-3-1",
            name="英语三年级上册",
            content_version_id=self.version_id,
        )

    async def get_book(
        self, _book_id: UUID, _bearer: str, _correlation_id: str | None
    ) -> CatalogBookDetail:
        return self.book

    async def list_book_courses(
        self, _book_id: UUID, _bearer: str, _correlation_id: str | None
    ) -> list[CatalogCourseView]:
        return [self.course]


class OutlineStub:
    def __init__(self, catalog: CatalogStub, *, available: bool = True) -> None:
        self.catalog = catalog
        self.available = available
        self.calls = 0

    async def get_outline(
        self,
        book_id: UUID,
        content_version_id: UUID,
        _bearer: str,
        _correlation_id: str | None,
    ) -> CatalogBookOutline:
        self.calls += 1
        return CatalogBookOutline(
            book_id=book_id,
            content_version_id=content_version_id,
            availability="available" if self.available else "unavailable",
            extractor_version="fixture-v1",
            provenance="pdf_bookmarks" if self.available else "none",
            confidence=1 if self.available else 0,
            reason=None if self.available else "no reliable outline",
            nodes=(
                CatalogOutlineNode(
                    id="unit-1",
                    ordinal=0,
                    title="Unit 1 Hello!",
                    page_start=4,
                    depth=0,
                ),
                CatalogOutlineNode(
                    id="unit-2",
                    ordinal=1,
                    title="Unit 2 Colours",
                    page_start=12,
                    depth=0,
                ),
            )
            if self.available
            else (),
        )


def harness(*, outline_available: bool = True):  # type: ignore[no-untyped-def]
    settings = Settings(environment=Environment.TEST, service_name="practice-api-test")
    app = create_app(settings)
    current = cast(Any, app).state.dependencies
    catalog = CatalogStub()
    outline = OutlineStub(catalog, available=outline_available)
    repository = InMemoryPracticeRepository()
    cast(Any, app).state.dependencies = PracticeDependencies(
        auth=current.auth,
        catalog=catalog,  # type: ignore[arg-type]
        outline=outline,
        repository=repository,
    )
    return TestClient(app), catalog, outline, repository


def test_outline_plan_and_idempotent_generation_are_observable_through_api() -> None:
    client, catalog, outline, _repository = harness()
    headers = {"Authorization": AUTHORIZATION}
    plan_response = client.get(
        f"/v1/practice/catalog/books/{catalog.book_id}/study-plan", headers=headers
    )
    assert plan_response.status_code == 200
    assert [item["title"] for item in plan_response.json()["modules"]] == [
        "Unit 1 Hello!",
        "Unit 2 Colours",
    ]

    generation_headers = {**headers, "Idempotency-Key": "browser-test-1"}
    first = client.post(
        f"/v1/practice/catalog/books/{catalog.book_id}/generations",
        headers=generation_headers,
        json={"count": 7, "language": "bilingual"},
    )
    replay = client.post(
        f"/v1/practice/catalog/books/{catalog.book_id}/generations",
        headers=generation_headers,
        json={"count": 3},
    )
    assert first.status_code == replay.status_code == 202
    assert first.json()["id"] == replay.json()["id"]
    assert replay.json()["requested_count"] == 7
    assert first.json()["status"] == "queued"
    assert outline.calls == 1

    legacy = client.post(
        f"/v1/practice/courses/{catalog.course_id}/exercises:generate",
        headers=generation_headers,
        json={"count": 7, "language": "bilingual"},
    )
    assert legacy.status_code == 202
    assert legacy.json()["id"] == first.json()["id"]

    status_response = client.get(f"/v1/practice/generations/{first.json()['id']}", headers=headers)
    assert status_response.json()["status"] == "queued"
    cancelled = client.post(
        f"/v1/practice/generations/{first.json()['id']}/cancel", headers=headers
    )
    assert cancelled.json()["status"] == "cancelled"


def test_unavailable_outline_uses_one_book_module_without_invented_objectives() -> None:
    client, catalog, _outline, _repository = harness(outline_available=False)
    response = client.get(
        f"/v1/practice/catalog/books/{catalog.book_id}/study-plan",
        headers={"Authorization": AUTHORIZATION},
    )
    assert response.status_code == 200
    assert response.json()["modules"] == [
        {
            "id": response.json()["modules"][0]["id"],
            "ordinal": 0,
            "title": catalog.book.title,
            "outline_node_id": None,
            "objectives": [],
        }
    ]


@pytest.mark.asyncio
async def test_lease_expiry_reclaims_job_without_creating_duplicate() -> None:
    repository = InMemoryPracticeRepository()
    catalog = CatalogStub()
    outline = OutlineStub(catalog)
    principal = Principal(
        user_id=uuid4(),
        tenant_id=uuid4(),
        role=UserRole.STUDENT,
        access_label=AccessLabel.ENROLLED,
        subject="learner",
        course_ids=frozenset({catalog.course_id}),
    )
    plan = await StudyPlanService(repository, outline).ensure_default(
        principal, catalog.book, catalog.course, "Bearer test", "corr"
    )
    job, created = await GenerationService(repository).submit(
        principal, plan, GeneratePracticeRequest(count=1), "lease-key", "corr"
    )
    assert created
    now = datetime.now(UTC)
    first = await repository.claim_next_generation("worker-a", now, timedelta(seconds=30))
    assert first is not None and first.attempt_count == 1
    assert (
        await repository.claim_next_generation(
            "worker-b", now + timedelta(seconds=10), timedelta(seconds=30)
        )
        is None
    )
    reclaimed = await repository.claim_next_generation(
        "worker-b", now + timedelta(seconds=31), timedelta(seconds=30)
    )
    assert reclaimed is not None
    assert reclaimed.id == job.id
    assert reclaimed.attempt_count == 2


@pytest.mark.asyncio
async def test_learner_set_never_serializes_protected_answer_or_rationale() -> None:
    repository = InMemoryPracticeRepository()
    catalog = CatalogStub()
    outline = OutlineStub(catalog)
    principal = Principal(
        user_id=uuid4(),
        tenant_id=uuid4(),
        role=UserRole.STUDENT,
        access_label=AccessLabel.ENROLLED,
        subject="learner",
        course_ids=frozenset({catalog.course_id}),
    )
    plan = await StudyPlanService(repository, outline).ensure_default(
        principal, catalog.book, catalog.course, "Bearer test", "corr"
    )
    job, _ = await GenerationService(repository).submit(
        principal, plan, GeneratePracticeRequest(count=1), "answer-key", "corr"
    )
    now = datetime.now(UTC)
    await repository.claim_next_generation("worker", now, timedelta(seconds=30))
    await repository.transition_generation(job.id, GenerationStatus.GENERATING)
    await repository.transition_generation(job.id, GenerationStatus.VALIDATING)
    value = await repository.complete_generation(
        job.id,
        (
            MultipleChoiceExerciseDraft(
                prompt="Which word means 你好?",
                difficulty=PracticeDifficulty.INTRODUCTORY,
                language=PracticeLanguage.BILINGUAL,
                evidence_citation_ids=("chunk-1",),
                options=(
                    ChoiceOption(id="a", text="hello"),
                    ChoiceOption(id="b", text="goodbye"),
                ),
                correct_option_id="a",
                rationale="The cited dialogue uses hello as the greeting.",
            ),
        ),
        seed=42,
        prompt_version="test",
        model_version="fake",
        validator_version="test",
    )
    rendered = value.exercises[0].model_dump_json()
    assert "correct_option_id" not in rendered
    assert "rationale" not in rendered
    assert "hello" in rendered

    replay, created = await GenerationService(repository).submit(
        principal, plan, GeneratePracticeRequest(count=1), "answer-key", "different-correlation"
    )
    assert created is False
    assert replay.id == job.id
    assert replay.practice_set_id == value.id


def test_generation_count_contract_enforces_default_and_bounds() -> None:
    assert GeneratePracticeRequest().count == 5
    assert GeneratePracticeRequest(count=1).count == 1
    assert GeneratePracticeRequest(count=20).count == 20
    with pytest.raises(ValueError):
        GeneratePracticeRequest(count=0)
    with pytest.raises(ValueError):
        GeneratePracticeRequest(count=21)
