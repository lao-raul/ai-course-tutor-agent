"""Shared bearer authentication and course-scope authorization.

Both product applications depend on this package. It deliberately contains no
database or Agent API imports so independently deployed apps share exactly the same
token-validation boundary without sharing internal application code.
"""

from __future__ import annotations

import asyncio
from collections.abc import Awaitable, Callable
from dataclasses import dataclass
from typing import Annotated, Any, Protocol, cast
from uuid import UUID

import jwt
from fastapi import Depends, HTTPException, Request, status
from fastapi.security import HTTPAuthorizationCredentials, HTTPBearer

from course_tutor_contracts.enums import AccessLabel, UserRole
from course_tutor_shared import AuthMode, Settings

_bearer = HTTPBearer(auto_error=False)


@dataclass(frozen=True, slots=True)
class Principal:
    user_id: UUID
    tenant_id: UUID
    role: UserRole
    access_label: AccessLabel
    subject: str
    course_ids: frozenset[UUID] | None = None


class AuthProvider(Protocol):
    async def authenticate(self, token: str) -> Principal: ...


def _claims_to_principal(claims: dict[str, Any]) -> Principal:
    try:
        raw_course_ids = claims.get("course_ids")
        course_ids = (
            frozenset(UUID(str(course_id)) for course_id in raw_course_ids)
            if raw_course_ids is not None
            else None
        )
        return Principal(
            user_id=UUID(str(claims["user_id"])),
            tenant_id=UUID(str(claims["tenant_id"])),
            role=UserRole(str(claims["role"])),
            access_label=AccessLabel(str(claims["access_label"])),
            subject=str(claims["sub"]),
            course_ids=course_ids,
        )
    except (KeyError, TypeError, ValueError) as exc:
        raise HTTPException(
            status_code=status.HTTP_401_UNAUTHORIZED,
            detail="token is missing required course-tutor claims",
        ) from exc


class LocalAuthProvider:
    """Deterministic development/test identity guarded by a fixed bearer token."""

    def __init__(self, settings: Settings) -> None:
        self._token = settings.local_auth_token.get_secret_value()
        self._principal = _claims_to_principal(
            {
                "sub": f"local:{settings.local_user_id}",
                "user_id": str(settings.local_user_id),
                "tenant_id": str(settings.local_tenant_id),
                "role": settings.local_user_role,
                "access_label": settings.local_access_label,
            }
        )

    async def authenticate(self, token: str) -> Principal:
        if not token or token != self._token:
            raise HTTPException(
                status_code=status.HTTP_401_UNAUTHORIZED,
                detail="invalid bearer token",
            )
        return self._principal


class OIDCAuthProvider:
    """Validate asymmetric OIDC JWTs against the configured JWKS endpoint."""

    def __init__(self, settings: Settings) -> None:
        if not settings.oidc_jwks_url or not settings.oidc_issuer or not settings.oidc_audience:
            raise ValueError("OIDC issuer, audience and JWKS URL are required")
        self._jwks = jwt.PyJWKClient(settings.oidc_jwks_url, cache_keys=True)
        self._issuer = settings.oidc_issuer.rstrip("/")
        self._audience = settings.oidc_audience
        self._algorithms = [item.strip() for item in settings.oidc_algorithms.split(",") if item]

    async def authenticate(self, token: str) -> Principal:
        try:
            signing_key = await asyncio.to_thread(self._jwks.get_signing_key_from_jwt, token)
            claims = jwt.decode(
                token,
                signing_key.key,
                algorithms=self._algorithms,
                audience=self._audience,
                issuer=self._issuer,
                options={"require": ["exp", "iat", "sub", "aud", "iss"]},
            )
        except jwt.PyJWTError as exc:
            raise HTTPException(
                status_code=status.HTTP_401_UNAUTHORIZED,
                detail="invalid or expired bearer token",
            ) from exc
        return _claims_to_principal(claims)


def create_auth_provider(settings: Settings) -> AuthProvider:
    if settings.auth_mode is AuthMode.OIDC:
        return OIDCAuthProvider(settings)
    return LocalAuthProvider(settings)


def get_auth_provider(request: Request) -> AuthProvider:
    return cast("AuthProvider", request.app.state.dependencies.auth)


async def get_current_principal(
    credentials: Annotated[HTTPAuthorizationCredentials | None, Depends(_bearer)],
    provider: Annotated[AuthProvider, Depends(get_auth_provider)],
) -> Principal:
    if credentials is None or credentials.scheme.lower() != "bearer":
        raise HTTPException(
            status_code=status.HTTP_401_UNAUTHORIZED,
            detail="bearer token required",
            headers={"WWW-Authenticate": "Bearer"},
        )
    return await provider.authenticate(credentials.credentials)


def require_roles(*allowed: UserRole) -> Callable[..., Awaitable[Principal]]:
    async def dependency(
        principal: Annotated[Principal, Depends(get_current_principal)],
    ) -> Principal:
        if principal.role not in allowed:
            raise HTTPException(status_code=status.HTTP_403_FORBIDDEN, detail="insufficient role")
        return principal

    return dependency


def principal_can_access_course(principal: Principal, course_id: UUID) -> bool:
    """Fail closed for learners unless membership is present in verified claims."""
    if principal.role in {UserRole.INSTRUCTOR, UserRole.PLATFORM_ADMIN}:
        return True
    return principal.course_ids is not None and course_id in principal.course_ids


require_course_admin = require_roles(UserRole.INSTRUCTOR, UserRole.PLATFORM_ADMIN)

__all__ = [
    "AuthProvider",
    "LocalAuthProvider",
    "OIDCAuthProvider",
    "Principal",
    "create_auth_provider",
    "get_current_principal",
    "principal_can_access_course",
    "require_course_admin",
]
