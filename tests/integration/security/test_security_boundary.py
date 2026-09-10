from __future__ import annotations

import uuid
from collections.abc import AsyncIterator
from datetime import UTC, datetime, timedelta
from types import SimpleNamespace

import httpx
import jwt
import pytest
from cryptography.hazmat.primitives.asymmetric import rsa
from fastapi import FastAPI, HTTPException
from httpx import ASGITransport, AsyncClient

from course_tutor_api.app import create_app
from course_tutor_api.auth import LocalAuthProvider, OIDCAuthProvider, create_auth_provider
from course_tutor_api.dependencies import Dependencies, get_session
from course_tutor_api.providers import FakeLLMProvider
from course_tutor_contracts.enums import AccessLabel
from course_tutor_shared import Settings
from course_tutor_shared.config import AuthMode, Environment


class _Redis:
    async def incr(self, _key: str) -> int:
        return 1

    async def expire(self, _key: str, _seconds: int) -> None:
        return None


class _Session:
    def __init__(self, course: object | None = None) -> None:
        self.course = course

    async def get(self, _model: object, _key: object) -> object | None:
        return self.course


def _wire(app: FastAPI, settings: Settings) -> None:
    app.state.settings = settings
    app.state.dependencies = Dependencies(
        settings=settings,
        engine=None,  # type: ignore[arg-type]
        redis=_Redis(),  # type: ignore[arg-type]
        http=httpx.AsyncClient(),
        llm=FakeLLMProvider(embedding_dimension=8),
        qdrant_client=None,  # type: ignore[arg-type]
        auth=create_auth_provider(settings),
    )


@pytest.mark.asyncio
async def test_anonymous_course_request_is_rejected(settings: Settings) -> None:
    app = create_app(settings)
    _wire(app, settings)

    async def fake_session() -> AsyncIterator[_Session]:
        yield _Session()

    app.dependency_overrides[get_session] = fake_session
    async with AsyncClient(transport=ASGITransport(app=app), base_url="http://test") as client:
        response = await client.get("/v1/courses")
    assert response.status_code == 401


@pytest.mark.asyncio
async def test_wrong_tenant_course_is_hidden(settings: Settings) -> None:
    app = create_app(settings)
    _wire(app, settings)
    other_tenant = uuid.uuid4()
    course_id = uuid.uuid4()

    async def fake_session() -> AsyncIterator[_Session]:
        yield _Session(
            SimpleNamespace(
                id=course_id,
                tenant_id=other_tenant,
                active_content_version_id=None,
            )
        )

    app.dependency_overrides[get_session] = fake_session
    async with AsyncClient(transport=ASGITransport(app=app), base_url="http://test") as client:
        response = await client.get(
            f"/v1/courses/{course_id}",
            headers={"Authorization": "Bearer local-dev-token"},
        )
    assert response.status_code == 404


@pytest.mark.asyncio
async def test_student_cannot_call_admin(settings: Settings) -> None:
    student = Settings(
        environment=Environment.TEST,
        auth_mode=AuthMode.LOCAL,
        local_user_role="student",
        local_access_label=AccessLabel.ENROLLED.value,
    )
    app = create_app(student)
    _wire(app, student)

    async def fake_session() -> AsyncIterator[_Session]:
        yield _Session()

    app.dependency_overrides[get_session] = fake_session
    async with AsyncClient(transport=ASGITransport(app=app), base_url="http://test") as client:
        response = await client.post(
            "/v1/admin/courses",
            headers={"Authorization": "Bearer local-dev-token"},
            json={
                "programme_id": str(uuid.uuid4()),
                "code": "COMP001",
                "name": "Example",
                "level": "postgraduate",
                "run_key": "2026-s1",
                "source_path": "/courses/example",
            },
        )
    assert response.status_code == 403


@pytest.mark.asyncio
async def test_local_provider_derives_identity_from_settings(settings: Settings) -> None:
    provider = LocalAuthProvider(settings)
    principal = await provider.authenticate("local-dev-token")
    assert principal.tenant_id == settings.local_tenant_id
    assert principal.user_id == settings.local_user_id
    assert principal.access_label is AccessLabel.RESTRICTED


def test_production_rejects_local_auth() -> None:
    with pytest.raises(ValueError, match="AUTH_MODE must be oidc"):
        Settings(
            environment=Environment.PRODUCTION,
            minio_secret_key="real-secret",
            auth_mode=AuthMode.LOCAL,
        )


@pytest.mark.asyncio
async def test_oidc_provider_verifies_signature_issuer_audience_and_expiry() -> None:
    tenant_id, user_id = uuid.uuid4(), uuid.uuid4()
    private_key = rsa.generate_private_key(public_exponent=65537, key_size=2048)
    now = datetime.now(UTC)
    token = jwt.encode(
        {
            "sub": "oidc-user",
            "user_id": str(user_id),
            "tenant_id": str(tenant_id),
            "role": "student",
            "access_label": "enrolled",
            "iss": "https://issuer.example",
            "aud": "course-tutor",
            "iat": now,
            "exp": now + timedelta(minutes=5),
        },
        private_key,
        algorithm="RS256",
    )
    provider = OIDCAuthProvider(
        Settings(
            environment=Environment.TEST,
            auth_mode=AuthMode.OIDC,
            oidc_issuer="https://issuer.example",
            oidc_audience="course-tutor",
            oidc_jwks_url="https://issuer.example/.well-known/jwks.json",
        )
    )
    provider._jwks = SimpleNamespace(  # type: ignore[assignment]
        get_signing_key_from_jwt=lambda _token: SimpleNamespace(key=private_key.public_key())
    )
    principal = await provider.authenticate(token)
    assert principal.tenant_id == tenant_id
    assert principal.user_id == user_id

    wrong_audience = OIDCAuthProvider(
        Settings(
            environment=Environment.TEST,
            auth_mode=AuthMode.OIDC,
            oidc_issuer="https://issuer.example",
            oidc_audience="another-service",
            oidc_jwks_url="https://issuer.example/.well-known/jwks.json",
        )
    )
    wrong_audience._jwks = provider._jwks  # type: ignore[assignment]
    with pytest.raises(HTTPException) as error:
        await wrong_audience.authenticate(token)
    assert error.value.status_code == 401


def test_openapi_exposes_bearer_auth_but_not_settings(settings: Settings) -> None:
    schema = create_app(settings).openapi()
    serialized = str(schema)
    request_schema = schema["paths"]["/v1/courses/{course_id}/chat"]["post"]["requestBody"]
    chat_schema = schema["components"]["schemas"]["ChatRequest"]
    assert "Settings" not in serialized
    assert "access_label" not in str(chat_schema)
    assert "query" in chat_schema["properties"]
    assert "ChatRequest" in str(request_schema)
    assert "HTTPBearer" in schema["components"]["securitySchemes"]
