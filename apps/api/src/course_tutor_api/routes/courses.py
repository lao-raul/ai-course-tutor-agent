"""Course listing and source browsing."""

from __future__ import annotations

import uuid
from collections.abc import AsyncGenerator
from typing import Annotated

from fastapi import APIRouter, Depends, HTTPException, status
from pydantic import BaseModel
from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession

from course_tutor_api.db import Course
from course_tutor_api.dependencies import get_dependencies

router = APIRouter(prefix="/v1/courses", tags=["courses"])


class CourseSummary(BaseModel, frozen=True):
    id: uuid.UUID
    code: str
    name: str
    level: str
    tenant_id: uuid.UUID
    active_content_version_id: uuid.UUID | None = None

    model_config = {"from_attributes": True}


async def get_session() -> AsyncGenerator[AsyncSession, None]:
    deps = get_dependencies()
    async with AsyncSession(deps.engine, expire_on_commit=False) as session:
        yield session


@router.get("", response_model=list[CourseSummary])
async def list_courses(
    session: Annotated[AsyncSession, Depends(get_session)],
) -> list[CourseSummary]:
    """List all courses the current tenant can access.

    For Phase 2 the tenant filter is a no-op (single-tenant); multi-tenant
    scoping arrives in Phase 4.
    """
    result = await session.execute(select(Course))
    courses = result.scalars().all()
    return [CourseSummary.model_validate(c) for c in courses]


@router.get("/{course_id}", response_model=CourseSummary)
async def get_course(
    course_id: uuid.UUID,
    session: Annotated[AsyncSession, Depends(get_session)],
) -> CourseSummary:
    """Get a single course by ID."""
    course = await session.get(Course, course_id)
    if course is None:
        raise HTTPException(status_code=status.HTTP_404_NOT_FOUND, detail="course not found")
    return CourseSummary.model_validate(course)
