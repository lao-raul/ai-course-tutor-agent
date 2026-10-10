"""Internal evidence API rejects untrusted scopes and withholds solutions."""

from __future__ import annotations

from datetime import UTC, datetime, timedelta
from types import SimpleNamespace
from uuid import uuid4

import pytest
from fastapi import HTTPException

from course_tutor_api.routes import practice_evidence
from course_tutor_api.routes.chat import EvidencePack
from course_tutor_auth import Principal
from course_tutor_auth.practice_delegation import issue_practice_delegation
from course_tutor_contracts import ChunkClass, PracticeEvidenceRequest, RetrievedChunk
from course_tutor_contracts.enums import AccessLabel, AnchorType, UserRole
from course_tutor_shared import Settings


class _Rows:
    def __init__(self, source_ids: tuple[object, ...]) -> None:
        self._source_ids = source_ids

    def all(self) -> tuple[object, ...]:
        return self._source_ids


class _Session:
    def __init__(self, source_ids: tuple[object, ...]) -> None:
        self.source_ids = source_ids

    async def scalars(self, _query):  # type: ignore[no-untyped-def]
        return _Rows(self.source_ids)


def _claims() -> tuple[PracticeEvidenceRequest, str]:
    principal = Principal(
        user_id=uuid4(),
        tenant_id=uuid4(),
        role=UserRole.STUDENT,
        access_label=AccessLabel.ENROLLED,
        subject="student",
    )
    request = PracticeEvidenceRequest(
        generation_id=uuid4(),
        book_id=uuid4(),
        course_id=uuid4(),
        content_version_id=uuid4(),
        query="Unit 1 greetings",
    )
    token = issue_practice_delegation(
        principal,
        generation_id=request.generation_id,
        book_id=request.book_id,
        course_id=request.course_id,
        content_version_id=request.content_version_id,
        expires_at=datetime.now(UTC) + timedelta(minutes=5),
        secret=Settings().practice_delegation_secret.get_secret_value(),
    )
    return request, token


@pytest.mark.asyncio
async def test_evidence_denies_missing_token_wrong_job_and_stale_publication() -> None:
    body, token = _claims()
    deps = SimpleNamespace(settings=Settings())
    with pytest.raises(HTTPException) as missing:
        await practice_evidence.retrieve_practice_evidence(
            body,
            _Session(()),
            deps,
            authorization=None,  # type: ignore[arg-type]
        )
    assert missing.value.status_code == 401

    wrong_job = body.model_copy(update={"generation_id": uuid4()})
    with pytest.raises(HTTPException) as mismatched:
        await practice_evidence.retrieve_practice_evidence(
            wrong_job,
            _Session(()),
            deps,
            authorization=f"Bearer {token}",  # type: ignore[arg-type]
        )
    assert mismatched.value.status_code == 403

    with pytest.raises(HTTPException) as unpublished:
        await practice_evidence.retrieve_practice_evidence(
            body,
            _Session(()),
            deps,
            authorization=f"Bearer {token}",  # type: ignore[arg-type]
        )
    assert unpublished.value.status_code == 404


@pytest.mark.asyncio
async def test_evidence_uses_pinned_scope_and_never_returns_solution_chunks(monkeypatch) -> None:  # type: ignore[no-untyped-def]
    body, token = _claims()
    source_id = uuid4()
    visible = RetrievedChunk(
        chunk_id=uuid4(),
        source_id=source_id,
        text="Hello is a greeting.",
        relative_path="grade-3.pdf",
        mime_type="application/pdf",
        anchor_type=AnchorType.PAGE,
        anchor_value="4",
        chunk_class=ChunkClass.CONTENT,
        score=0.9,
    )
    solution = visible.model_copy(
        update={
            "chunk_id": uuid4(),
            "text": "Protected model answer",
            "chunk_class": ChunkClass.EXERCISE_SOLUTION,
        }
    )
    pack = EvidencePack(
        candidates=(visible, solution),
        evidence=(visible, solution),
        citation_map={},
        timings_ms={},
    )
    observed: dict[str, object] = {}

    async def retrieve(**kwargs):  # type: ignore[no-untyped-def]
        observed.update(kwargs)
        return pack

    async def trace(*_args, **_kwargs):  # type: ignore[no-untyped-def]
        return uuid4()

    monkeypatch.setattr(practice_evidence, "_build_evidence_pack", retrieve)
    monkeypatch.setattr(practice_evidence, "_create_trace", trace)
    monkeypatch.setattr(practice_evidence, "_get_retrieval_service", lambda _deps: object())
    monkeypatch.setattr(practice_evidence, "_get_reranker", lambda: object())
    result = await practice_evidence.retrieve_practice_evidence(
        body,
        _Session((source_id,)),  # type: ignore[arg-type]
        SimpleNamespace(settings=Settings()),  # type: ignore[arg-type]
        authorization=f"Bearer {token}",
    )
    assert result.content_version_id == body.content_version_id
    assert [chunk.chunk_id for chunk in result.chunks] == [visible.chunk_id]
    assert observed["source_ids"] == (source_id,)
    assert observed["version_id"] == body.content_version_id
    assert observed["access_label"] is AccessLabel.ENROLLED
