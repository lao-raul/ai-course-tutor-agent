"""Course listing and source browsing."""

from __future__ import annotations

import uuid
from typing import Annotated

from fastapi import APIRouter, Depends, HTTPException, status
from pydantic import BaseModel
from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession

from course_tutor_api.auth import Principal, get_current_principal
from course_tutor_api.db import ContentVersion, Course, SourceDocument
from course_tutor_api.dependencies import get_session
from course_tutor_contracts.enums import AccessLabel

router = APIRouter(prefix="/v1/courses", tags=["courses"])


class CourseSummary(BaseModel, frozen=True):
    id: uuid.UUID
    programme_id: uuid.UUID
    code: str
    name: str
    level: str
    tenant_id: uuid.UUID
    active_content_version_id: uuid.UUID | None = None

    model_config = {"from_attributes": True}


class CourseSourceDetail(BaseModel, frozen=True):
    id: uuid.UUID
    relative_path: str
    mime_type: str
    checksum: str
    access_label: AccessLabel
    extraction_status: str
    failure_reason: str | None
    artifact_key: str | None


_ACCESS_RANK = {
    AccessLabel.PUBLIC: 0,
    AccessLabel.ENROLLED: 1,
    AccessLabel.STAFF_ONLY: 2,
    AccessLabel.RESTRICTED: 3,
}


@router.get("", response_model=list[CourseSummary])
async def list_courses(
    session: Annotated[AsyncSession, Depends(get_session)],
    principal: Annotated[Principal, Depends(get_current_principal)],
) -> list[CourseSummary]:
    """List all courses the current tenant can access.

    Tenant scope is derived from the verified principal.
    """
    result = await session.execute(select(Course).where(Course.tenant_id == principal.tenant_id))
    courses = result.scalars().all()
    return [CourseSummary.model_validate(c) for c in courses]


@router.get("/{course_id}", response_model=CourseSummary)
async def get_course(
    course_id: uuid.UUID,
    session: Annotated[AsyncSession, Depends(get_session)],
    principal: Annotated[Principal, Depends(get_current_principal)],
) -> CourseSummary:
    """Get a single course by ID."""
    course = await session.get(Course, course_id)
    if course is None or course.tenant_id != principal.tenant_id:
        raise HTTPException(status_code=status.HTTP_404_NOT_FOUND, detail="course not found")
    return CourseSummary.model_validate(course)


@router.get("/{course_id}/sources/{source_id}", response_model=CourseSourceDetail)
async def get_course_source(
    course_id: uuid.UUID,
    source_id: uuid.UUID,
    session: Annotated[AsyncSession, Depends(get_session)],
    principal: Annotated[Principal, Depends(get_current_principal)],
) -> CourseSourceDetail:
    """Return metadata for one source in the authorized active content version."""
    result = await session.execute(
        select(SourceDocument)
        .join(ContentVersion, SourceDocument.version_id == ContentVersion.id)
        .join(Course, ContentVersion.course_id == Course.id)
        .where(
            SourceDocument.id == source_id,
            Course.id == course_id,
            Course.tenant_id == principal.tenant_id,
            Course.active_content_version_id == ContentVersion.id,
        )
    )
    source = result.scalar_one_or_none()
    if source is None or _ACCESS_RANK[source.access_label] > _ACCESS_RANK[principal.access_label]:
        raise HTTPException(status_code=status.HTTP_404_NOT_FOUND, detail="source not found")
    return CourseSourceDetail(
        id=source.id,
        relative_path=source.relative_path,
        mime_type=source.mime_type,
        checksum=source.checksum,
        access_label=source.access_label,
        extraction_status=source.extraction_status.value,
        failure_reason=source.failure_reason,
        artifact_key=source.artifact_key,
    )
