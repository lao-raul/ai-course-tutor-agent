"""Short-lived, job-bound user delegation for the asynchronous practice worker."""

from __future__ import annotations

from datetime import UTC, datetime
from uuid import UUID

import jwt
from pydantic import BaseModel, ConfigDict

from course_tutor_auth import Principal
from course_tutor_contracts.enums import AccessLabel

ISSUER = "course-tutor-practice"
AUDIENCE = "course-tutor-agent-practice-evidence"


class PracticeDelegation(BaseModel):
    model_config = ConfigDict(extra="forbid", frozen=True)

    generation_id: UUID
    tenant_id: UUID
    user_id: UUID
    book_id: UUID
    course_id: UUID
    content_version_id: UUID
    access_label: AccessLabel


def issue_practice_delegation(
    principal: Principal,
    *,
    generation_id: UUID,
    book_id: UUID,
    course_id: UUID,
    content_version_id: UUID,
    expires_at: datetime,
    secret: str,
) -> str:
    if len(secret) < 24:
        raise ValueError("practice delegation secret is too short")
    claims = PracticeDelegation(
        generation_id=generation_id,
        tenant_id=principal.tenant_id,
        user_id=principal.user_id,
        book_id=book_id,
        course_id=course_id,
        content_version_id=content_version_id,
        access_label=principal.access_label,
    )
    return jwt.encode(
        {
            **claims.model_dump(mode="json"),
            "iss": ISSUER,
            "aud": AUDIENCE,
            "sub": str(principal.user_id),
            "iat": datetime.now(UTC),
            "exp": expires_at,
        },
        secret,
        algorithm="HS256",
    )


def verify_practice_delegation(token: str, secret: str) -> PracticeDelegation:
    if len(secret) < 24:
        raise ValueError("practice delegation secret is too short")
    claims = jwt.decode(
        token,
        secret,
        algorithms=["HS256"],
        issuer=ISSUER,
        audience=AUDIENCE,
        options={"require": ["iss", "aud", "sub", "iat", "exp"]},
    )
    delegation = PracticeDelegation.model_validate(
        {
            key: value
            for key, value in claims.items()
            if key not in {"iss", "aud", "sub", "iat", "exp"}
        }
    )
    if claims["sub"] != str(delegation.user_id):
        raise jwt.InvalidTokenError("delegation subject mismatch")
    return delegation
