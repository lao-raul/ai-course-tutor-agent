"""Tenant-authorized reads of published, versioned textbook outlines."""

from __future__ import annotations

from typing import Annotated
from uuid import UUID

from fastapi import APIRouter, Depends, HTTPException, Query, status
from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession

from course_tutor_api.auth import Principal, get_current_principal
from course_tutor_api.db import (
    Book,
    BookContentBinding,
    BookOutline,
    ContentVersion,
    Course,
    CourseRun,
)
from course_tutor_api.dependencies import get_session
from course_tutor_contracts import CatalogBookOutline, CatalogOutlineNode
from course_tutor_contracts.enums import BookLifecycleStatus, ContentVersionStatus

router = APIRouter(prefix="/v1/catalog", tags=["catalog"])


@router.get(
    "/books/{book_id}/outline",
    response_model=CatalogBookOutline,
    operation_id="getCatalogBookOutline",
)
async def get_catalog_book_outline(
    book_id: UUID,
    session: Annotated[AsyncSession, Depends(get_session)],
    principal: Annotated[Principal, Depends(get_current_principal)],
    content_version_id: Annotated[UUID | None, Query()] = None,
) -> CatalogBookOutline:
    """Only serve the outline attached to the currently published content version."""
    query = (
        select(BookOutline)
        .join(Book, Book.id == BookOutline.book_id)
        .join(
            BookContentBinding,
            (BookContentBinding.book_id == BookOutline.book_id)
            & (BookContentBinding.content_version_id == BookOutline.content_version_id),
        )
        .join(CourseRun, CourseRun.id == BookContentBinding.course_run_id)
        .join(Course, Course.id == CourseRun.course_id)
        .join(ContentVersion, ContentVersion.id == BookOutline.content_version_id)
        .where(
            Book.id == book_id,
            Book.tenant_id == principal.tenant_id,
            Book.lifecycle_status == BookLifecycleStatus.PUBLISHED,
            ContentVersion.status == ContentVersionStatus.PUBLISHED,
            CourseRun.active_content_version_id == BookOutline.content_version_id,
            Course.active_content_version_id == BookOutline.content_version_id,
        )
        .order_by(BookOutline.created_at.desc())
    )
    if content_version_id is not None:
        query = query.where(BookOutline.content_version_id == content_version_id)
    result = await session.execute(query.limit(1))
    outline = result.scalar_one_or_none()
    if outline is None:
        # Same response for absent, stale and cross-tenant resources.
        raise HTTPException(status_code=status.HTTP_404_NOT_FOUND, detail="book outline not found")
    nodes = tuple(CatalogOutlineNode.model_validate(node) for node in outline.nodes)
    return CatalogBookOutline.model_validate(
        {
            "book_id": outline.book_id,
            "content_version_id": outline.content_version_id,
            "availability": outline.availability,
            "extractor_version": outline.extractor_version,
            "provenance": outline.provenance,
            "confidence": outline.confidence,
            "reason": outline.reason,
            "nodes": nodes if outline.availability == "available" else (),
        }
    )
