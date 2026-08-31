"""Admin routes: course setup and ingestion management.

Design (function-spec FR-1):
  POST /v1/admin/ingest          → creates Tenant / Course / SourceRoot /
                                    initial BUILDING ContentVersion / OutboxEvent
  GET  /v1/admin/ingestions/{id}  → polling status
  POST /v1/admin/courses/{id}/versions/{vid}/publish
  POST /v1/admin/courses/{id}/versions/{vid}/rollback
"""

from __future__ import annotations

import uuid
from collections.abc import AsyncGenerator
from datetime import UTC, datetime
from typing import Annotated
from uuid import UUID

from course_tutor_ingestion import SourceRootError, validate_path, validate_read_access
from fastapi import APIRouter, Depends, HTTPException, status
from pydantic import BaseModel, Field
from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession

from course_tutor_api.db import ContentVersion, Course, SourceRoot, Tenant
from course_tutor_api.db.models import OutboxEvent
from course_tutor_api.dependencies import get_dependencies
from course_tutor_contracts.enums import ContentVersionStatus, EducationLevel

router = APIRouter(prefix="/v1/admin", tags=["admin"])

# Bumped whenever the parsing or chunking algorithm changes to force a full re-index.
PIPELINE_VERSION = "1.0.0"


# ---------------------------------------------------------------------------
# Request / Response shapes
# ---------------------------------------------------------------------------


class IngestRequest(BaseModel):
    """One-shot course setup + ingestion queue.

    Phase 1 covers the happy path: one course per tenant, one module run.
    Multi-course and multi-tenant management is Phase 4.
    """

    tenant_slug: str = Field(..., min_length=1, max_length=64)
    tenant_name: str = Field(..., min_length=1, max_length=255)
    course_code: str = Field(..., min_length=1, max_length=64)
    course_name: str = Field(..., min_length=1, max_length=255)
    course_level: EducationLevel
    source_path: str = Field(..., min_length=1)

    model_config = {"extra": "forbid"}


class IngestResponse(BaseModel, frozen=True):
    tenant_id: UUID
    course_id: UUID
    source_root_id: UUID
    version_id: UUID
    job_id: UUID
    resolved_path: str


class IngestionStatusResponse(BaseModel, frozen=True):
    job_id: str
    topic: str
    status: str
    attempts: int
    processed_at: str | None
    dead_lettered_at: str | None
    last_error: str | None


class VersionActionResponse(BaseModel, frozen=True):
    version_id: UUID
    status: str
    published_at: str | None


# ---------------------------------------------------------------------------
# Dependencies
# ---------------------------------------------------------------------------


async def get_session() -> AsyncGenerator[AsyncSession, None]:
    deps = get_dependencies()
    async with AsyncSession(deps.engine, expire_on_commit=False) as session:
        yield session


# ---------------------------------------------------------------------------
# Routes
# ---------------------------------------------------------------------------


@router.post(
    "/ingest",
    response_model=IngestResponse,
    status_code=status.HTTP_201_CREATED,
)
async def ingest(
    body: IngestRequest,
    session: Annotated[AsyncSession, Depends(get_session)],
) -> IngestResponse:
    """Register a course, source root, initial BUILDING version, and queue a scan job.

    All created in one transaction. The worker consumes the outbox event asynchronously.
    """
    # 1. Validate source path (OS-level).
    try:
        resolved = validate_path(body.source_path)
        validate_read_access(resolved)
    except SourceRootError as exc:
        raise HTTPException(status_code=status.HTTP_400_BAD_REQUEST, detail=str(exc)) from exc

    # 2. Tenant — create if not exists.
    tenant_id = uuid.uuid4()
    tenant = Tenant(id=tenant_id, slug=body.tenant_slug, name=body.tenant_name)
    session.add(tenant)
    await session.flush()  # Ensure tenant_id is visible to SourceRoot FK

    # 3. SourceRoot.
    source_root_id = uuid.uuid4()
    source_root = SourceRoot(
        id=source_root_id,
        tenant_id=tenant_id,
        absolute_path=str(resolved),
        last_scanned_at=None,
    )
    session.add(source_root)
    await session.flush()  # Ensure source_root_id is visible to Course FK

    # 4. Course — linked to the source root.
    course_id = uuid.uuid4()
    course = Course(
        id=course_id,
        tenant_id=tenant_id,
        code=body.course_code,
        name=body.course_name,
        level=body.course_level,
        source_root_id=source_root_id,
        teaching_policy={},
    )
    session.add(course)
    await session.flush()  # Ensure course_id is visible to ContentVersion FK

    # 5. Initial BUILDING content version.
    version_id = uuid.uuid4()
    version = ContentVersion(
        id=version_id,
        course_id=course_id,
        pipeline_version=PIPELINE_VERSION,
        sequence=1,
        status=ContentVersionStatus.BUILDING,
        embedding_model_version="text-embedding-qwen3-embedding-0.6b",
        embedding_dimension=1024,
    )
    session.add(version)

    # 6. Outbox event (idempotency key = scan:{tenant_id}:{resolved_path}).
    job_id = uuid.uuid4()
    outbox_event = OutboxEvent(
        id=job_id,
        topic="ingestion.scan",
        idempotency_key=f"scan:{tenant_id}:{resolved}",
        payload={
            "tenant_id": str(tenant_id),
            "course_id": str(course_id),
            "source_root_id": str(source_root_id),
            "version_id": str(version_id),
            "resolved_path": str(resolved),
        },
        attempts=0,
    )
    session.add(outbox_event)
    await session.commit()

    return IngestResponse(
        tenant_id=tenant_id,
        course_id=course_id,
        source_root_id=source_root_id,
        version_id=version_id,
        job_id=job_id,
        resolved_path=str(resolved),
    )


@router.get("/ingestions/{job_id}", response_model=IngestionStatusResponse)
async def get_ingestion_status(
    job_id: UUID,
    session: Annotated[AsyncSession, Depends(get_session)],
) -> IngestionStatusResponse:
    """Poll the status of an ingestion job."""
    event = await session.get(OutboxEvent, job_id)
    if event is None or event.topic != "ingestion.scan":
        raise HTTPException(status_code=status.HTTP_404_NOT_FOUND, detail=f"job {job_id} not found")

    return IngestionStatusResponse(
        job_id=str(event.id),
        topic=event.topic,
        status="pending"
        if event.processed_at is None and event.dead_lettered_at is None
        else "dead_lettered"
        if event.dead_lettered_at is not None
        else "processed",
        attempts=event.attempts,
        processed_at=event.processed_at.isoformat() if event.processed_at else None,
        dead_lettered_at=event.dead_lettered_at.isoformat() if event.dead_lettered_at else None,
        last_error=event.last_error,
    )


@router.post(
    "/courses/{course_id}/versions/{version_id}/publish",
    response_model=VersionActionResponse,
)
async def publish_version(
    course_id: UUID,
    version_id: UUID,
    session: Annotated[AsyncSession, Depends(get_session)],
) -> VersionActionResponse:
    """Publish a READY version and atomically make it the course's active version.

    No data is modified — this is an alias swap (function-spec FR-1.3).
    """
    version = await session.get(ContentVersion, version_id)
    if version is None or version.course_id != course_id:
        raise HTTPException(status_code=status.HTTP_404_NOT_FOUND, detail="version not found")

    if version.status != ContentVersionStatus.READY:
        raise HTTPException(
            status_code=status.HTTP_400_BAD_REQUEST,
            detail=(
                f"version status is {version.status.value}, "
                f"must be {ContentVersionStatus.READY.value}"
            ),
        )

    now = datetime.now(UTC).replace(tzinfo=None)
    version.status = ContentVersionStatus.PUBLISHED
    version.published_at = now

    course = await session.get(Course, course_id)
    if course is None:
        raise HTTPException(status_code=status.HTTP_404_NOT_FOUND, detail="course not found")

    course.active_content_version_id = version_id
    await session.commit()

    return VersionActionResponse(
        version_id=version_id,
        status="published",
        published_at=now.isoformat(),
    )


@router.post(
    "/courses/{course_id}/versions/{version_id}/rollback",
    response_model=VersionActionResponse,
)
async def rollback_version(
    course_id: UUID,
    version_id: UUID,
    session: Annotated[AsyncSession, Depends(get_session)],
) -> VersionActionResponse:
    """Roll back the active version by switching the alias to the previous published version.

    Only the active version can be rolled back (function-spec FR-1.3).
    """
    course = await session.get(Course, course_id)
    if course is None:
        raise HTTPException(status_code=status.HTTP_404_NOT_FOUND, detail="course not found")

    if course.active_content_version_id != version_id:
        raise HTTPException(
            status_code=status.HTTP_400_BAD_REQUEST,
            detail="can only rollback the currently active version",
        )

    # Find the previous published version ordered by published_at desc.
    result = await session.execute(
        select(ContentVersion)
        .where(
            ContentVersion.course_id == course_id,
            ContentVersion.id != version_id,
            ContentVersion.status == ContentVersionStatus.PUBLISHED,
        )
        .order_by(ContentVersion.published_at.desc())
        .limit(1)
    )
    prev = result.scalar_one_or_none()
    if prev is None:
        raise HTTPException(
            status_code=status.HTTP_400_BAD_REQUEST,
            detail="no previous published version to roll back to",
        )

    version = await session.get(ContentVersion, version_id)
    version.status = ContentVersionStatus.ROLLED_BACK  # type: ignore[union-attr]
    course.active_content_version_id = prev.id
    await session.commit()

    return VersionActionResponse(
        version_id=version_id,
        status="rolled_back",
        published_at=prev.published_at.isoformat() if prev.published_at else None,
    )
