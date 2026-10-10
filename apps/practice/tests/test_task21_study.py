"""Task-21 learner-facing policy, replay, authorization and projection checks."""

from __future__ import annotations

import asyncio
import json
import uuid
from dataclasses import replace
from datetime import UTC, datetime, timedelta
from typing import Any, cast
from uuid import UUID

import httpx
from fastapi.testclient import TestClient

from course_tutor_contracts import (
    BookLifecycleStatus,
    CatalogBookDetail,
    CatalogCourseView,
    ChoiceOption,
    EducationLevel,
    FillInTheBlankExerciseDraft,
    GenerationStatus,
    MultipleChoiceExerciseDraft,
    PracticeDifficulty,
    PracticeLanguage,
    RubricCriterion,
    ShortAnswerExerciseDraft,
    TrueFalseExerciseDraft,
)
from course_tutor_practice.adapters.agent_client import AgentCatalogError
from course_tutor_practice.adapters.memory_repository import InMemoryPracticeRepository
from course_tutor_practice.app import PracticeDependencies, create_app
from course_tutor_practice.domain import GenerationRecord, ModuleRecord, StudyPlanRecord
from course_tutor_practice.domain.policies import feedback
from course_tutor_shared import Settings
from course_tutor_shared.config import Environment

SETTINGS = Settings(environment=Environment.TEST, service_name="practice-task21-test")
HEADERS = {"Authorization": f"Bearer {SETTINGS.local_auth_token.get_secret_value()}"}


class CatalogStub:
    def __init__(self) -> None:
        self.book_id = uuid.uuid4()
        self.course_id = uuid.uuid4()
        self.version_id = uuid.uuid4()
        self.denied = False

    async def get_book(
        self, book_id: UUID, _bearer: str, _correlation_id: str | None
    ) -> CatalogBookDetail:
        if self.denied or book_id != self.book_id:
            raise AgentCatalogError(403, "denied")
        return CatalogBookDetail(
            id=book_id,
            title="English Grade 3",
            education_level=EducationLevel.PRIMARY,
            subject="英语",
            grade="3",
            publisher="外研社",
            series="外研社版",
            term="上册",
            language="en",
            lifecycle_status=BookLifecycleStatus.PUBLISHED,
        )

    async def list_book_courses(
        self, book_id: UUID, _bearer: str, _correlation_id: str | None
    ) -> list[CatalogCourseView]:
        if self.denied or book_id != self.book_id:
            raise AgentCatalogError(403, "denied")
        return [
            CatalogCourseView(
                course_id=self.course_id,
                course_run_id=uuid.uuid4(),
                code="EN-3",
                name="English Grade 3",
                content_version_id=self.version_id,
            )
        ]


class RubricStub:
    model_version = "fake-rubric-v1"

    async def score(
        self, *, answer: str, exemplar: str, criteria: tuple[str, ...], correlation_id: str
    ) -> tuple[float, ...]:
        assert exemplar and criteria
        return tuple(0.8 if "hello" in answer.lower() else 0.2 for _ in criteria)


def _drafts() -> tuple[Any, ...]:
    citation = str(uuid.uuid4())
    common: dict[str, Any] = {
        "difficulty": PracticeDifficulty.STANDARD,
        "language": PracticeLanguage.EN,
        "evidence_citation_ids": (citation,),
        "rationale": "The textbook explains the answer. PROTECTED-RATIONALE",
    }
    return (
        MultipleChoiceExerciseDraft(
            **common,
            prompt="Which is a greeting?",
            options=(
                ChoiceOption(id="a", text="Hello"),
                ChoiceOption(id="b", text="Goodbye"),
            ),
            correct_option_id="a",
        ),
        TrueFalseExerciseDraft(**common, prompt="Hello is a greeting.", answer=True),
        FillInTheBlankExerciseDraft(
            **common, prompt="Say ___ to greet someone.", acceptable_answers=("Hello",)
        ),
        ShortAnswerExerciseDraft(
            **common,
            prompt="Explain a greeting.",
            rubric=(RubricCriterion(description="Explains use", weight=1),),
            exemplar_answer="Hello is used when greeting someone.",
        ),
    )


def harness() -> tuple[TestClient, CatalogStub, InMemoryPracticeRepository, UUID, tuple[UUID, ...]]:
    app = create_app(SETTINGS)
    dependencies = cast(Any, app).state.dependencies
    repo = InMemoryPracticeRepository()
    catalog = CatalogStub()
    cast(Any, app).state.dependencies = PracticeDependencies(
        auth=dependencies.auth,
        catalog=catalog,  # type: ignore[arg-type]
        repository=repo,
        rubric_evaluator=RubricStub(),
    )
    module = ModuleRecord(id=uuid.uuid4(), ordinal=0, title="Unit 1")
    plan = StudyPlanRecord(
        id=uuid.uuid4(),
        tenant_id=SETTINGS.local_tenant_id,
        book_id=catalog.book_id,
        course_id=catalog.course_id,
        course_run_id=uuid.uuid4(),
        content_version_id=catalog.version_id,
        name="Default plan",
        revision=1,
        modules=(module,),
    )
    repo.plans[plan.id] = plan
    now = datetime.now(UTC)
    generation = GenerationRecord(
        id=uuid.uuid4(),
        tenant_id=SETTINGS.local_tenant_id,
        user_id=SETTINGS.local_user_id,
        study_plan_id=plan.id,
        module_id=module.id,
        book_id=catalog.book_id,
        course_id=catalog.course_id,
        course_run_id=plan.course_run_id,
        content_version_id=catalog.version_id,
        idempotency_key="seed",
        request_payload={},
        requested_count=4,
        status=GenerationStatus.VALIDATING,
        correlation_id="task21",
        deadline_at=now + timedelta(minutes=5),
        attempt_count=1,
        created_at=now,
        updated_at=now,
    )
    repo.generations[generation.id] = generation
    practice_set = asyncio.run(
        repo.complete_generation(
            generation.id,
            _drafts(),
            seed=1,
            prompt_version="test",
            model_version="test",
            validator_version="test",
        )
    )
    return (
        TestClient(app),
        catalog,
        repo,
        practice_set.id,
        tuple(item.id for item in practice_set.exercises),
    )


def _submit(
    client: TestClient, set_id: UUID, exercise_id: UUID, answer: str | bool, key: str
) -> httpx.Response:
    return cast(
        "httpx.Response",
        client.post(
            f"/v1/practice/sets/{set_id}/exercises/{exercise_id}/attempts",
            headers={**HEADERS, "Idempotency-Key": key},
            json={"answer": answer},
        ),
    )


def test_three_attempt_release_replay_progress_and_no_early_leakage() -> None:
    client, _catalog, repo, set_id, exercises = harness()
    set_response = client.get(f"/v1/practice/sets/{set_id}", headers=HEADERS)
    assert set_response.status_code == 200
    assert "PROTECTED-RATIONALE" not in set_response.text
    assert "correct_option_id" not in set_response.text
    assert "exemplar_answer" not in set_response.text

    first = _submit(client, set_id, exercises[0], "b", "try-1")
    assert first.status_code == 200
    assert first.json()["attempt_number"] == 1
    assert first.json()["hint"]
    assert first.json()["released_answer"] is None
    assert _submit(client, set_id, exercises[0], "b", "try-1").json() == first.json()
    assert _submit(client, set_id, exercises[0], "a", "try-1").status_code == 409
    second = _submit(client, set_id, exercises[0], "b", "try-2")
    assert second.json()["attempt_number"] == 2
    assert second.json()["hint"] != first.json()["hint"]
    assert second.json()["released_answer"] is None
    assert "PROTECTED-RATIONALE" not in json.dumps(second.json())
    third = _submit(client, set_id, exercises[0], "b", "try-3")
    assert third.json()["attempt_number"] == 3
    assert third.json()["released_answer"]["answer"] == "a"
    assert "PROTECTED-RATIONALE" in third.text
    assert _submit(client, set_id, exercises[0], "b", "try-4").status_code == 409
    assert _submit(client, set_id, exercises[0], "b", "try-1").json() == first.json()

    status_response = client.get("/v1/practice/study-status", headers=HEADERS)
    assert status_response.status_code == 200
    assert "PROTECTED-RATIONALE" not in status_response.text
    status = status_response.json()["sets"][0]
    assert (
        status["attempted_questions"],
        status["completed_questions"],
        status["correct_questions"],
    ) == (1, 1, 0)
    assert status["topic_mastery"]
    plan_status = status_response.json()["plans"][0]
    assert plan_status["study_plan_id"] == status["study_plan_id"]
    assert plan_status["completed_questions"] == 1
    assert plan_status["status"] == "IN_PROGRESS"
    before = repo.progress[(SETTINGS.local_tenant_id, SETTINGS.local_user_id, set_id)]
    repo.progress.clear()
    rebuilt = asyncio.run(
        repo.rebuild_progress(SETTINGS.local_tenant_id, SETTINGS.local_user_id, set_id)
    )
    assert rebuilt == before
    assert len(repo.attempts) == 3
    assert len(repo.activities) == 3


def test_objective_short_answer_give_up_and_report_without_solution_leakage() -> None:
    client, _catalog, _repo, set_id, exercises = harness()
    assert _submit(client, set_id, exercises[1], "true", "bad-bool").status_code == 422
    assert _submit(client, set_id, exercises[1], True, "tf-1").json()["correct"] is True
    assert (
        _submit(client, set_id, exercises[2], "  ＨＥＬＬＯ  ", "fill-1").json()["correct"] is True  # noqa: RUF001
    )
    short = _submit(client, set_id, exercises[3], "hello", "short-1")
    assert short.status_code == 200
    assert short.json()["provisional"] is True
    assert short.json()["evaluator_version"] == "fake-rubric-v1"
    assert short.json()["score"] == 0.8
    assert short.json()["released_answer"] is None
    report = client.post(
        f"/v1/practice/exercises/{exercises[3]}/reports",
        headers={**HEADERS, "Idempotency-Key": "report-1"},
        json={"reason": "ambiguous", "detail": "Question needs review"},
    )
    assert report.status_code == 200
    assert report.json()["status"] == "open"
    assert "PROTECTED-RATIONALE" not in report.text
    assert (
        client.post(
            f"/v1/practice/exercises/{exercises[3]}/reports",
            headers={**HEADERS, "Idempotency-Key": "report-1"},
            json={"reason": "unsafe", "detail": "Different report"},
        ).status_code
        == 409
    )
    after_correct = client.post(
        f"/v1/practice/sets/{set_id}/exercises/{exercises[1]}/give-up",
        headers={**HEADERS, "Idempotency-Key": "explain-correct"},
    )
    assert after_correct.json()["released_answer"]["answer"] is True
    give_up = client.post(
        f"/v1/practice/sets/{set_id}/exercises/{exercises[0]}/give-up",
        headers={**HEADERS, "Idempotency-Key": "giveup-1"},
    )
    assert give_up.status_code == 200
    assert give_up.json()["released_answer"]["answer"] == "a"
    assert (
        client.post(
            f"/v1/practice/sets/{set_id}/exercises/{exercises[0]}/give-up",
            headers={**HEADERS, "Idempotency-Key": "giveup-1"},
        ).json()
        == give_up.json()
    )


def test_resume_rechecks_access_reset_preserves_history_and_memory_requires_consent() -> None:
    client, catalog, repo, set_id, exercises = harness()
    assert _submit(client, set_id, exercises[0], "b", "attempt-1").status_code == 200
    resume = client.get("/v1/practice/resume", headers=HEADERS)
    assert resume.status_code == 200
    assert resume.json()["exercise_id"] == str(exercises[0])
    assert resume.json()["attempt_number"] == 1
    assert "answer" not in resume.text
    assert (
        client.get("/v1/practice/study-status/memory-signals", headers=HEADERS).status_code == 403
    )
    assert client.put(
        "/v1/practice/study-status/memory-consent",
        headers=HEADERS,
        json={"enabled": True},
    ).json() == {"enabled": True}
    signals = client.get("/v1/practice/study-status/memory-signals", headers=HEADERS)
    assert signals.status_code == 200
    assert signals.json()[0]["schema_version"] == "hiruzen.study.v1"
    assert "answer" not in signals.text
    catalog.denied = True
    assert client.get("/v1/practice/resume", headers=HEADERS).json() is None
    assert client.get(f"/v1/practice/sets/{set_id}", headers=HEADERS).status_code == 404
    assert _submit(client, set_id, exercises[0], "b", "attempt-2").status_code == 404
    catalog.denied = False
    reset = client.delete("/v1/practice/resume", headers={**HEADERS, "Idempotency-Key": "reset-1"})
    assert reset.status_code == 204
    assert client.get("/v1/practice/resume", headers=HEADERS).json() is None
    assert len(repo.attempts) == 1
    assert _submit(client, set_id, exercises[0], "b", "attempt-2").status_code == 200
    assert client.get("/v1/practice/resume", headers=HEADERS).json() is not None


def test_other_user_cannot_read_or_submit_owned_set() -> None:
    client, _catalog, repo, set_id, exercises = harness()
    original = repo.sets[set_id]
    repo.sets[set_id] = replace(original, user_id=uuid.uuid4())
    assert client.get(f"/v1/practice/sets/{set_id}", headers=HEADERS).status_code == 404
    assert _submit(client, set_id, exercises[0], "b", "stolen").status_code == 404


def test_resume_falls_back_to_latest_accessible_set_when_cursor_version_is_revoked() -> None:
    client, catalog, repo, old_set_id, old_exercises = harness()
    assert _submit(client, old_set_id, old_exercises[0], "b", "old-attempt").status_code == 200
    source_job = repo.generations[repo.sets[old_set_id].generation_id]
    second_job = replace(
        source_job,
        id=uuid.uuid4(),
        idempotency_key="seed-two",
        status=GenerationStatus.VALIDATING,
    )
    repo.generations[second_job.id] = second_job
    fresh = asyncio.run(
        repo.complete_generation(
            second_job.id,
            _drafts(),
            seed=2,
            prompt_version="test",
            model_version="test",
            validator_version="test",
        )
    )
    stale_version = uuid.uuid4()
    repo.sets[old_set_id] = replace(repo.sets[old_set_id], content_version_id=stale_version)
    key = (SETTINGS.local_tenant_id, SETTINGS.local_user_id, old_set_id)
    repo.progress[key] = repo.progress[key].model_copy(update={"content_version_id": stale_version})
    assert catalog.version_id != stale_version
    resume = client.get("/v1/practice/resume", headers=HEADERS)
    assert resume.status_code == 200
    assert resume.json()["practice_set_id"] == str(fresh.id)
    assert resume.json()["exercise_id"] == str(fresh.exercises[0].id)
    historical = client.get("/v1/practice/study-status", headers=HEADERS)
    assert historical.status_code == 200
    assert {item["practice_set_id"] for item in historical.json()["sets"]} == {
        str(old_set_id),
        str(fresh.id),
    }
    assert client.get(f"/v1/practice/sets/{old_set_id}", headers=HEADERS).status_code == 404


def test_short_answer_dependency_failure_does_not_consume_an_attempt() -> None:
    client, _catalog, repo, set_id, exercises = harness()
    dependencies = cast(Any, client.app).state.dependencies
    cast(Any, client.app).state.dependencies = replace(dependencies, rubric_evaluator=None)
    assert _submit(client, set_id, exercises[3], "hello", "rubric-down").status_code == 503
    assert len(repo.attempts) == 0


def test_hints_follow_chinese_english_or_bilingual_question_language() -> None:
    client, _catalog, repo, set_id, exercises = harness()
    assert _submit(client, set_id, exercises[0], "b", "language-1").status_code == 200
    material = asyncio.run(
        repo.get_material(SETTINGS.local_tenant_id, SETTINGS.local_user_id, set_id, exercises[0])
    )
    assert material is not None
    attempt = repo.attempts[0]
    chinese = feedback(
        replace(material, view=material.view.model_copy(update={"language": PracticeLanguage.ZH})),
        attempt,
    )
    bilingual = feedback(
        replace(
            material,
            view=material.view.model_copy(update={"language": PracticeLanguage.BILINGUAL}),
        ),
        attempt,
    )
    assert chinese.hint and "教材" in chinese.hint
    assert bilingual.hint and " / " in bilingual.hint
