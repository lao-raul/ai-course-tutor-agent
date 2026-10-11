"""Protected preview requires explicit teacher assignment, never role alone."""

from dataclasses import replace
from uuid import uuid4

from course_tutor_auth import Principal
from course_tutor_contracts.enums import AccessLabel, UserRole
from course_tutor_practice.application.preview import can_preview_course


def test_preview_requires_tenant_role_and_explicit_course_assignment() -> None:
    tenant, course = uuid4(), uuid4()
    instructor = Principal(
        user_id=uuid4(),
        tenant_id=tenant,
        role=UserRole.INSTRUCTOR,
        access_label=AccessLabel.STAFF_ONLY,
        subject="teacher",
        course_ids=frozenset({course}),
    )
    assert can_preview_course(instructor, tenant_id=tenant, course_id=course)
    for role in (UserRole.STUDENT, UserRole.TEACHING_ASSISTANT, UserRole.PLATFORM_ADMIN):
        assert not can_preview_course(
            replace(instructor, role=role), tenant_id=tenant, course_id=course
        )
    for assigned in (None, frozenset(), frozenset({uuid4()})):
        assert not can_preview_course(
            replace(instructor, course_ids=assigned), tenant_id=tenant, course_id=course
        )
    assert not can_preview_course(instructor, tenant_id=uuid4(), course_id=course)
