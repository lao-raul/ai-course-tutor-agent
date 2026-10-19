"""Authorization boundary for the instructor-only protected preview read model."""

from uuid import UUID

from course_tutor_auth import Principal
from course_tutor_contracts.enums import UserRole


def can_preview_course(principal: Principal, *, tenant_id: UUID, course_id: UUID) -> bool:
    """Require both tenant isolation and explicit instructor course assignment.

    Platform administration alone does not grant access to protected answers.
    The caller must additionally validate the exact book/version and publication.
    """
    return (
        principal.tenant_id == tenant_id
        and principal.role == UserRole.INSTRUCTOR
        and principal.course_ids is not None
        and course_id in principal.course_ids
    )
