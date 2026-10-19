"""Preview checks authorization and durable audit before returning protected data."""

from types import SimpleNamespace
from unittest.mock import AsyncMock, Mock
from uuid import uuid4

import pytest
from fastapi import FastAPI
from fastapi.testclient import TestClient

from course_tutor_auth import Principal, get_current_principal
from course_tutor_contracts.enums import AccessLabel, UserRole
from course_tutor_practice.routes import preview


@pytest.fixture
def setup_preview(monkeypatch):  # type: ignore[no-untyped-def]
    tenant, course, book, version, set_id = (uuid4() for _ in range(5))
    model = SimpleNamespace(
        id=set_id,
        tenant_id=tenant,
        agent_course_id=course,
        agent_book_id=book,
        agent_content_version_id=version,
        model_version="fake",
        prompt_version="p1",
        validator_version="v1",
    )
    row = SimpleNamespace(
        id=uuid4(),
        ordinal=0,
        fingerprint="immutable-revision",
        presentation={
            "type": "true_false",
            "prompt": "A greeting?",
            "difficulty": "standard",
            "language": "en",
            "evidence_citation_ids": [str(uuid4())],
        },
        protected_answer={"answer": True},
        rationale="protected rationale",
    )
    row.evidence_citation_ids = row.presentation["evidence_citation_ids"]
    session = SimpleNamespace(
        scalar=AsyncMock(return_value=model),
        scalars=AsyncMock(return_value=SimpleNamespace(all=lambda: [row])),
        add=Mock(),
        commit=AsyncMock(),
    )
    catalog = SimpleNamespace(resolve_citations=AsyncMock(return_value=[]))
    app = FastAPI()
    app.include_router(preview.router)
    principal = Principal(
        uuid4(), tenant, UserRole.INSTRUCTOR, AccessLabel.STAFF_ONLY, "teacher", frozenset({course})
    )
    app.dependency_overrides[get_current_principal] = lambda: principal
    app.dependency_overrides[preview.preview_session] = lambda: session
    app.dependency_overrides[preview._catalog] = lambda: catalog
    access = AsyncMock(return_value=True)
    monkeypatch.setattr(preview, "ensure_published_access", access)
    return app, principal, session, model, access


def test_preview_audits_redacted_metadata_and_disables_cache(setup_preview):  # type: ignore[no-untyped-def]
    app, _, session, model, _ = setup_preview
    response = TestClient(app).get(
        f"/v1/practice/sets/{model.id}/preview", headers={"Authorization": "Bearer test"}
    )
    assert response.status_code == 200
    assert response.headers["cache-control"] == "no-store"
    assert response.json()["exercises"][0]["question"]["answer"] is True
    assert response.json()["official_assessment"] is False
    audit = session.add.call_args.args[0]
    assert audit.set_id == model.id
    assert "answer" not in vars(audit) and "rationale" not in vars(audit)
    session.commit.assert_awaited_once()


@pytest.mark.parametrize(
    "role", [UserRole.STUDENT, UserRole.TEACHING_ASSISTANT, UserRole.PLATFORM_ADMIN]
)
def test_preview_denies_non_instructors_before_storage(setup_preview, role):  # type: ignore[no-untyped-def]
    from dataclasses import replace

    app, principal, session, model, _ = setup_preview
    app.dependency_overrides[get_current_principal] = lambda: replace(principal, role=role)
    response = TestClient(app).get(
        f"/v1/practice/sets/{model.id}/preview", headers={"Authorization": "Bearer test"}
    )
    assert response.status_code == 403
    session.scalar.assert_not_awaited()


@pytest.mark.parametrize("failure", ["tenant", "course", "publication", "missing", "audit"])
def test_preview_fails_closed(setup_preview, failure):  # type: ignore[no-untyped-def]
    app, _, session, model, access = setup_preview
    if failure == "tenant":
        model.tenant_id = uuid4()
    elif failure == "course":
        model.agent_course_id = uuid4()
    elif failure == "publication":
        access.return_value = False
    elif failure == "missing":
        session.scalar.return_value = None
    else:
        session.commit.side_effect = RuntimeError("audit unavailable")
    response = TestClient(app, raise_server_exceptions=False).get(
        f"/v1/practice/sets/{model.id}/preview", headers={"Authorization": "Bearer test"}
    )
    assert response.status_code == (500 if failure == "audit" else 404)
    assert "protected rationale" not in response.text
