from __future__ import annotations

import os
import uuid
from pathlib import Path

import httpx
import pytest
from course_tutor_ingestion.embed_jobs import _process_embed_event
from course_tutor_ingestion.jobs import IngestionJob
from course_tutor_retrieval.collection import COLLECTION_NAME, recreate_collection
from course_tutor_retrieval.indexer import EmbeddingIndexer
from course_tutor_retrieval.search import DenseRetrievalService
from qdrant_client import QdrantClient
from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncEngine, AsyncSession

from course_tutor_api.auth import Principal, create_auth_provider
from course_tutor_api.db import OutboxEvent, Tenant
from course_tutor_api.dependencies import Dependencies
from course_tutor_api.providers import FakeLLMProvider
from course_tutor_api.routes.admin import (
    CourseRegistrationRequest,
    ProgrammeRegistrationRequest,
    publish_version,
    queue_ingestion,
    register_course,
    register_programme,
)
from course_tutor_api.routes.chat import (
    _build_evidence_pack,
    _create_trace,
    _event_stream,
    _get_reranker,
)
from course_tutor_api.routes.courses import list_courses
from course_tutor_contracts.enums import AccessLabel, EducationLevel, UserRole
from course_tutor_contracts.retrieval import ChatRequest
from course_tutor_shared import Settings
from course_tutor_shared.config import Environment


@pytest.mark.asyncio
async def test_generated_course_ingest_publish_ask_with_citation(
    db_session: AsyncSession,
    integration_db_engine: AsyncEngine,
    tmp_path: Path,
) -> None:
    qdrant_url = os.environ.get("TEST_QDRANT_URL")
    if not qdrant_url:
        pytest.skip("TEST_QDRANT_URL is required; use scripts/run-integration-tests.sh")

    source_root = tmp_path / "generated-course"
    source_root.mkdir()
    (source_root / "week1.md").write_text(
        "# Bayes rule\nBayes rule updates a prior probability using observed evidence.",
        encoding="utf-8",
    )

    tenant_id = uuid.uuid4()
    principal = Principal(
        user_id=uuid.uuid4(),
        tenant_id=tenant_id,
        role=UserRole.INSTRUCTOR,
        access_label=AccessLabel.RESTRICTED,
        subject="e2e-instructor",
    )
    db_session.add(Tenant(id=tenant_id, slug="e2e", name="E2E Tenant"))
    await db_session.commit()
    programme = await register_programme(
        ProgrammeRegistrationRequest(code="E2E-AI", name="Generated AI"),
        db_session,
        principal,
    )
    course = await register_course(
        CourseRegistrationRequest(
            programme_id=programme.programme_id,
            code="E2E-COURSE",
            name="Generated Course",
            level=EducationLevel.POSTGRADUATE,
            run_key="2026-test",
            source_path=str(source_root),
        ),
        db_session,
        principal,
    )
    queued = await queue_ingestion(course.course_id, db_session, principal, "e2e")
    scan_event = await db_session.get(OutboxEvent, queued.job_id)
    assert scan_event is not None
    await IngestionJob(db_session, scan_event).run()

    embed_event = (
        await db_session.execute(select(OutboxEvent).where(OutboxEvent.topic == "ingestion.embed"))
    ).scalar_one()
    settings = Settings(
        environment=Environment.TEST,
        llm_embedding_dimension=1024,
        llm_chat_model="fake-chat",
        llm_embedding_model="fake-embedding",
    )
    embedder = FakeLLMProvider(embedding_dimension=1024)
    qdrant = QdrantClient(url=qdrant_url)
    await recreate_collection(qdrant)
    indexer = EmbeddingIndexer(qdrant, embedder)
    await _process_embed_event(db_session, embed_event, indexer, "fake-embedding")
    await db_session.commit()
    version_id = uuid.UUID(str(embed_event.payload["version_id"]))
    await publish_version(course.course_id, version_id, db_session, principal)

    listed = await list_courses(db_session, principal)
    assert [item.id for item in listed] == [course.course_id]

    retrieval = DenseRetrievalService(qdrant, embedder)
    pack = await _build_evidence_pack(
        retrieval,
        _get_reranker(),
        tenant_id,
        course.course_id,
        version_id,
        principal.access_label,
        "How does Bayes rule use evidence?",
    )
    assert pack.evidence
    cited_chunk_id = pack.evidence[0].chunk_id
    llm = FakeLLMProvider(
        embedding_dimension=1024,
        reply=(
            "Bayes rule updates a prior using evidence [Source 1].\n"
            f'CITATIONS:[{{"source":1,"chunk_id":"{cited_chunk_id}"}}]'
        ),
    )
    http = httpx.AsyncClient()
    deps = Dependencies(
        settings=settings,
        engine=integration_db_engine,
        redis=None,  # type: ignore[arg-type]
        http=http,
        llm=llm,
        qdrant_client=qdrant,
        auth=create_auth_provider(settings),
    )
    trace_id = await _create_trace(
        db_session,
        deps,
        course.course_id,
        version_id,
        "How does Bayes rule use evidence?",
        pack,
        stream_state="started",
    )
    response = "".join(
        [event async for event in _event_stream(deps, trace_id, ChatRequest(query="Bayes"), pack)]
    )
    assert "event: token" in response
    assert "event: citation" in response
    assert str(cited_chunk_id) in response
    assert "CITATIONS:" not in response

    await http.aclose()
    qdrant.delete_collection(COLLECTION_NAME)
    qdrant.close()
