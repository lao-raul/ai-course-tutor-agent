"""Cross-service generation: HTTP Agent evidence, Practice worker and protected read model."""

from __future__ import annotations

from uuid import uuid4

import httpx
import pytest
from course_tutor_practice_worker.grounded import GroundedGenerationExecutor
from course_tutor_practice_worker.worker import PracticeWorker
from sqlalchemy.ext.asyncio import AsyncSession

from course_tutor_api.app import create_app
from course_tutor_api.dependencies import dependencies_from_request, get_session
from course_tutor_api.routes import practice_evidence
from course_tutor_api.routes.chat import EvidencePack
from course_tutor_auth import Principal
from course_tutor_contracts import (
    ChoiceOption,
    ChunkClass,
    GeneratePracticeRequest,
    MultipleChoiceExerciseDraft,
    PracticeDifficulty,
    PracticeLanguage,
    RetrievedChunk,
)
from course_tutor_contracts.enums import AccessLabel, AnchorType, UserRole
from course_tutor_practice.adapters.agent_client import HttpAgentEvidenceProvider
from course_tutor_practice.adapters.memory_repository import InMemoryPracticeRepository
from course_tutor_practice.application.generation import GenerationService
from course_tutor_practice.domain import ModuleRecord, StudyPlanRecord
from course_tutor_practice.generation.schemas import GeneratedBatch
from course_tutor_shared import Settings
from tests.integration.practice.test_evidence_access import _published_book


@pytest.mark.asyncio
async def test_published_agent_evidence_produces_a_safe_practice_set(
    db_session: AsyncSession, settings: Settings, monkeypatch: pytest.MonkeyPatch
) -> None:
    tenant, book, course, version = await _published_book(db_session)
    evidence_chunk = RetrievedChunk(
        chunk_id=uuid4(),
        source_id=uuid4(),
        text="Unit 1: Hello is a greeting. Children say Hello when meeting a friend.",
        relative_path="grade-3-english.pdf",
        mime_type="application/pdf",
        anchor_type=AnchorType.PAGE,
        anchor_value="4",
        chunk_class=ChunkClass.CONTENT,
        score=0.9,
    )

    async def retrieve(**_kwargs):  # type: ignore[no-untyped-def]
        return EvidencePack(
            candidates=(evidence_chunk,),
            evidence=(evidence_chunk,),
            citation_map={},
            timings_ms={},
        )

    async def trace(*_args, **_kwargs):  # type: ignore[no-untyped-def]
        return uuid4()

    monkeypatch.setattr(practice_evidence, "_build_evidence_pack", retrieve)
    monkeypatch.setattr(practice_evidence, "_create_trace", trace)
    monkeypatch.setattr(practice_evidence, "_get_retrieval_service", lambda _deps: object())
    monkeypatch.setattr(practice_evidence, "_get_reranker", lambda: object())

    app = create_app(settings)
    app.dependency_overrides[get_session] = lambda: db_session
    app.dependency_overrides[dependencies_from_request] = lambda: type(
        "Deps", (), {"settings": settings}
    )()
    principal = Principal(
        user_id=uuid4(),
        tenant_id=tenant.id,
        role=UserRole.STUDENT,
        access_label=AccessLabel.ENROLLED,
        subject="student",
    )
    plan = StudyPlanRecord(
        id=uuid4(),
        tenant_id=tenant.id,
        book_id=book.id,
        course_id=course.id,
        course_run_id=version.course_run_id,
        content_version_id=version.id,
        name="Grade 3 English",
        revision=1,
        modules=(ModuleRecord(id=uuid4(), ordinal=0, title="Unit 1"),),
    )
    repository = InMemoryPracticeRepository()
    await repository.save_study_plan(plan)
    job, _ = await GenerationService(
        repository, settings.practice_delegation_secret.get_secret_value()
    ).submit(
        principal,
        plan,
        GeneratePracticeRequest(count=1, module_id=plan.modules[0].id),
        "e2e-key",
        "e2e-correlation",
    )

    class Inference:
        model = "deterministic-e2e"

        async def generate_json(
            self, _messages: list[dict[str, str]], _seed: int, _correlation_id: str
        ) -> str:
            draft = MultipleChoiceExerciseDraft(
                prompt="哪一个是见面时使用的问候语?",
                options=(
                    ChoiceOption(id="a", text="Hello"),
                    ChoiceOption(id="b", text="Goodbye"),
                ),
                correct_option_id="a",
                difficulty=PracticeDifficulty.STANDARD,
                language=PracticeLanguage.ZH,
                evidence_citation_ids=(str(evidence_chunk.chunk_id),),
                rationale="教材说明 Hello 是问候语。",
            )
            return GeneratedBatch(exercises=(draft,)).model_dump_json()

    async with httpx.AsyncClient(
        transport=httpx.ASGITransport(app=app), base_url="http://agent.test"
    ) as http:
        executor = GroundedGenerationExecutor(
            HttpAgentEvidenceProvider("http://agent.test", http), Inference()
        )
        worker = PracticeWorker(repository, executor, worker_id="e2e-worker")
        assert await worker.run_once()

    completed = await repository.get_generation(tenant.id, principal.user_id, job.id)
    assert completed is not None and completed.status.value == "ready"
    assert completed.practice_set_id is not None
    safe_set = await repository.get_practice_set(
        tenant.id, principal.user_id, completed.practice_set_id
    )
    assert safe_set is not None and len(safe_set.exercises) == 1
    safe_exercise = safe_set.exercises[0].model_dump_json()
    assert "correct_option_id" not in safe_exercise
    assert str(evidence_chunk.chunk_id) in safe_exercise
