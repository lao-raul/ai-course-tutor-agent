"""Database-backed course authorization for normal and system textbook runs."""

from __future__ import annotations

from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession

from course_tutor_api.auth import Principal, principal_can_access_course
from course_tutor_api.db import Course, CourseRun
from course_tutor_contracts.enums import CourseAccessPolicy


async def principal_can_access_course_record(
    session: AsyncSession,
    principal: Principal,
    course: Course,
) -> bool:
    """Authorize a persisted course without trusting request-provided policy fields."""
    if course.tenant_id != principal.tenant_id:
        return False
    if principal_can_access_course(principal, course.id):
        return True
    result = await session.execute(
        select(CourseRun.id)
        .where(
            CourseRun.course_id == course.id,
            CourseRun.access_policy == CourseAccessPolicy.TENANT_AUTHENTICATED,
        )
        .limit(1)
    )
    return result.first() is not None


__all__ = ["principal_can_access_course_record"]
