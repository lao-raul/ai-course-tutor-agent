"""Tenant-scoped course, ingestion and immutable-version administration."""

from __future__ import annotations

import uuid
from datetime import UTC, datetime
from pathlib import Path
from typing import Annotated, Any
from uuid import UUID

from course_tutor_memory import TeachingPolicy
from fastapi import APIRouter, Depends, Header, HTTPException, status
from pydantic import BaseModel, Field
from sqlalchemy import select
from sqlalchemy.exc import IntegrityError
from sqlalchemy.ext.asyncio import AsyncSession

from course_tutor_api.auth import Principal, get_current_principal, require_course_admin
from course_tutor_api.db import (
    AuditEvent,
    ContentVersion,
    ContentVersionSource,
    Course,
    CourseRun,
    OutboxEvent,
    Programme,
    SourceDocument,
    SourceRoot,
    Tenant,
)
from course_tutor_api.dependencies import (
    Dependencies,
    RedisRateLimiter,
    dependencies_from_request,
    get_session,
)
from course_tutor_contracts.enums import ContentVersionStatus, EducationLevel
from course_tutor_shared import PIPELINE_VERSION, record_content_version_operation


async def _enforce_admin_rate_limit(
    principal: Annotated[Principal, Depends(get_current_principal)],
    dependencies: Annotated[Dependencies, Depends(dependencies_from_request)],
) -> None:
    await RedisRateLimiter(dependencies.redis).enforce(
        f"admin:{principal.tenant_id}:{principal.user_id}", limit=120, window_seconds=60
    )


router = APIRouter(
    prefix="/v1/admin",
    tags=["admin"],
    dependencies=[Depends(_enforce_admin_rate_limit)],
)


class CourseRegistrationRequest(BaseModel):
    programme_id: UUID
    code: str = Field(..., min_length=1, max_length=64)
    name: str = Field(..., min_length=1, max_length=255)
    level: EducationLevel
    run_key: str = Field(..., min_length=1, max_length=128)
    source_path: str = Field(..., min_length=1)
    scan_interval_seconds: int = Field(default=900, ge=30)
    automatic_ingestion_enabled: bool = True

    model_config = {"extra": "forbid"}


class ProgrammeRegistrationRequest(BaseModel):
    code: str = Field(..., min_length=1, max_length=64)
    name: str = Field(..., min_length=1, max_length=255)

    model_config = {"extra": "forbid"}


class ProgrammeRegistrationResponse(BaseModel, frozen=True):
    programme_id: UUID


class ProgrammeSummaryResponse(BaseModel, frozen=True):
    programme_id: UUID
    code: str
    name: str


class CourseRegistrationResponse(BaseModel, frozen=True):
    course_id: UUID
    course_run_id: UUID
    source_root_id: UUID
    resolved_path: str


class CourseRegistrationDetailResponse(CourseRegistrationResponse, frozen=True):
    programme_id: UUID
    code: str
    name: str
    level: str
    run_key: str
    scan_interval_seconds: int
    automatic_ingestion_enabled: bool


class IngestionQueuedResponse(BaseModel, frozen=True):
    job_id: UUID
    course_id: UUID
    version_id: UUID | None = None
    status: str = "pending"


class IngestionStatusResponse(BaseModel, frozen=True):
    job_id: UUID
    course_id: UUID
    version_id: UUID | None
    status: str
    version_status: str | None
    attempts: int
    processed_at: datetime | None
    dead_lettered_at: datetime | None
    last_error: str | None
    stats: dict[str, Any] = Field(default_factory=dict)


class SourceStatusResponse(BaseModel, frozen=True):
    id: UUID
    version_id: UUID
    relative_path: str
    checksum: str
    extraction_status: str
    failure_reason: str | None
    artifact_key: str | None


class VersionActionResponse(BaseModel, frozen=True):
    version_id: UUID
    active_version_id: UUID
    status: str
    published_at: datetime | None


class ContentVersionSummaryResponse(BaseModel, frozen=True):
    version_id: UUID
    sequence: int
    status: str
    source_snapshot_hash: str | None
    embedding_model_version: str
    embedding_dimension: int
    published_at: datetime | None


class TeachingPolicyResponse(BaseModel, frozen=True):
    course_id: UUID
    policy: TeachingPolicy


def _validated_source_path(raw: str) -> str:
    if "://" in raw:
        raise HTTPException(
            status_code=status.HTTP_422_UNPROCESSABLE_ENTITY,
            detail="source_path must be a mounted local absolute path, not a URL",
        )
    path = Path(raw)
    if not path.is_absolute():
        raise HTTPException(
            status_code=status.HTTP_422_UNPROCESSABLE_ENTITY,
            detail="source_path must be absolute",
        )
    # The ingestion worker, not the API pod, owns the read-only NAS mount.
    return str(path)


def _audit(
    session: AsyncSession,
    principal: Principal,
    action: str,
    resource_type: str,
    resource_id: UUID | str,
    **details: Any,
) -> None:
    session.add(
        AuditEvent(
            id=uuid.uuid4(),
            tenant_id=principal.tenant_id,
            actor_user_id=principal.user_id,
            action=action,
            resource_type=resource_type,
            resource_id=str(resource_id),
            details=details,
        )
    )


async def _tenant_course(session: AsyncSession, course_id: UUID, principal: Principal) -> Course:
    course = await session.get(Course, course_id)
    if course is None or course.tenant_id != principal.tenant_id:
        raise HTTPException(status_code=status.HTTP_404_NOT_FOUND, detail="course not found")
    return course


@router.put(
    "/courses/{course_id}/teaching-policy",
    response_model=TeachingPolicyResponse,
    operation_id="setTeachingPolicy",
)
async def set_teaching_policy(
    course_id: UUID,
    body: TeachingPolicy,
    session: Annotated[AsyncSession, Depends(get_session)],
    principal: Annotated[Principal, Depends(require_course_admin)],
) -> TeachingPolicyResponse:
    course = await _tenant_course(session, course_id, principal)
    course.teaching_policy = body.model_dump(mode="json")
    _audit(session, principal, "teaching_policy.update", "course", course.id)
    await session.commit()
    return TeachingPolicyResponse(course_id=course.id, policy=body)


@router.post(
    "/programmes",
    response_model=ProgrammeRegistrationResponse,
    status_code=status.HTTP_201_CREATED,
)
async def register_programme(
    body: ProgrammeRegistrationRequest,
    session: Annotated[AsyncSession, Depends(get_session)],
    principal: Annotated[Principal, Depends(require_course_admin)],
) -> ProgrammeRegistrationResponse:
    if await session.get(Tenant, principal.tenant_id) is None:
        raise HTTPException(status_code=409, detail="authenticated tenant is not provisioned")
    programme = Programme(
        id=uuid.uuid4(), tenant_id=principal.tenant_id, code=body.code, name=body.name
    )
    session.add(programme)
    _audit(session, principal, "programme.register", "programme", programme.id)
    try:
        await session.commit()
    except IntegrityError as exc:
        await session.rollback()
        raise HTTPException(status_code=409, detail="programme code already exists") from exc
    return ProgrammeRegistrationResponse(programme_id=programme.id)


@router.get("/programmes", response_model=list[ProgrammeSummaryResponse])
async def list_programmes(
    session: Annotated[AsyncSession, Depends(get_session)],
    principal: Annotated[Principal, Depends(require_course_admin)],
    code: str | None = None,
) -> list[ProgrammeSummaryResponse]:
    query = select(Programme).where(Programme.tenant_id == principal.tenant_id)
    if code is not None:
        query = query.where(Programme.code == code)
    result = await session.execute(query.order_by(Programme.code))
    return [
        ProgrammeSummaryResponse(programme_id=item.id, code=item.code, name=item.name)
        for item in result.scalars().all()
    ]


@router.post(
    "/courses",
    response_model=CourseRegistrationResponse,
    status_code=status.HTTP_201_CREATED,
)
async def register_course(
    body: CourseRegistrationRequest,
    session: Annotated[AsyncSession, Depends(get_session)],
    principal: Annotated[Principal, Depends(require_course_admin)],
) -> CourseRegistrationResponse:
    """Register metadata and a source root without starting ingestion."""
    if await session.get(Tenant, principal.tenant_id) is None:
        raise HTTPException(
            status_code=status.HTTP_409_CONFLICT,
            detail="authenticated tenant is not provisioned",
        )
    programme = await session.get(Programme, body.programme_id)
    if programme is None or programme.tenant_id != principal.tenant_id:
        raise HTTPException(status_code=404, detail="programme not found")
    resolved = _validated_source_path(body.source_path)
    source_root = SourceRoot(
        id=uuid.uuid4(),
        tenant_id=principal.tenant_id,
        absolute_path=resolved,
        last_scanned_at=None,
        last_snapshot_hash=None,
        scan_interval_seconds=body.scan_interval_seconds,
        automatic_ingestion_enabled=body.automatic_ingestion_enabled,
    )
    course = Course(
        id=uuid.uuid4(),
        tenant_id=principal.tenant_id,
        programme_id=programme.id,
        code=body.code,
        name=body.name,
        level=body.level,
        source_root_id=source_root.id,
        teaching_policy={},
    )
    session.add(source_root)
    await session.flush()
    session.add(course)
    await session.flush()
    course_run = CourseRun(
        id=uuid.uuid4(),
        course_id=course.id,
        run_key=body.run_key,
        source_root_id=source_root.id,
        active_content_version_id=None,
    )
    session.add(course_run)
    _audit(session, principal, "course.register", "course", course.id, source_path=resolved)
    try:
        await session.commit()
    except IntegrityError as exc:
        await session.rollback()
        raise HTTPException(
            status_code=status.HTTP_409_CONFLICT,
            detail="course code already exists in this tenant",
        ) from exc
    return CourseRegistrationResponse(
        course_id=course.id,
        course_run_id=course_run.id,
        source_root_id=source_root.id,
        resolved_path=resolved,
    )


@router.get(
    "/courses/{course_id}/registration",
    response_model=CourseRegistrationDetailResponse,
)
async def get_course_registration(
    course_id: UUID,
    session: Annotated[AsyncSession, Depends(get_session)],
    principal: Annotated[Principal, Depends(require_course_admin)],
) -> CourseRegistrationDetailResponse:
    course = await _tenant_course(session, course_id, principal)
    if course.source_root_id is None:
        raise HTTPException(status_code=409, detail="course registration is incomplete")
    source_root = await session.get(SourceRoot, course.source_root_id)
    run_result = (
        await session.execute(
            select(CourseRun)
            .where(CourseRun.course_id == course.id, CourseRun.source_root_id == source_root.id)
            .order_by(CourseRun.created_at.desc())
            .limit(1)
        )
        if source_root is not None
        else None
    )
    course_run = run_result.scalar_one_or_none() if run_result is not None else None
    if source_root is None or course_run is None:
        raise HTTPException(status_code=409, detail="course registration is incomplete")
    return CourseRegistrationDetailResponse(
        course_id=course.id,
        course_run_id=course_run.id,
        source_root_id=source_root.id,
        resolved_path=source_root.absolute_path,
        programme_id=course.programme_id,
        code=course.code,
        name=course.name,
        level=course.level.value,
        run_key=course_run.run_key,
        scan_interval_seconds=source_root.scan_interval_seconds,
        automatic_ingestion_enabled=source_root.automatic_ingestion_enabled,
    )


@router.post(
    "/courses/{course_id}/ingestions",
    response_model=IngestionQueuedResponse,
    status_code=status.HTTP_202_ACCEPTED,
)
async def queue_ingestion(
    course_id: UUID,
    session: Annotated[AsyncSession, Depends(get_session)],
    principal: Annotated[Principal, Depends(require_course_admin)],
    idempotency_key: Annotated[str | None, Header(alias="Idempotency-Key")] = None,
) -> IngestionQueuedResponse:
    """Queue an incremental scan for an already registered course."""
    course = await _tenant_course(session, course_id, principal)
    if course.source_root_id is None:
        raise HTTPException(status_code=409, detail="course has no source root")
    source_root = await session.get(SourceRoot, course.source_root_id)
    if source_root is None or source_root.tenant_id != principal.tenant_id:
        raise HTTPException(status_code=409, detail="course source root is invalid")
    run_result = await session.execute(
        select(CourseRun)
        .where(CourseRun.course_id == course.id, CourseRun.source_root_id == source_root.id)
        .order_by(CourseRun.created_at.desc())
        .limit(1)
    )
    course_run = run_result.scalar_one_or_none()
    if course_run is None:
        raise HTTPException(status_code=409, detail="course has no registered run")

    pending_result = await session.execute(
        select(OutboxEvent)
        .where(
            OutboxEvent.topic == "ingestion.scan",
            OutboxEvent.processed_at.is_(None),
            OutboxEvent.dead_lettered_at.is_(None),
            OutboxEvent.payload["course_id"].astext == str(course.id),
        )
        .order_by(OutboxEvent.created_at)
        .limit(1)
    )
    if pending := pending_result.scalar_one_or_none():
        raw_version = pending.payload.get("version_id")
        return IngestionQueuedResponse(
            job_id=pending.id,
            course_id=course_id,
            version_id=UUID(raw_version) if raw_version else None,
        )

    event_key = f"scan:{course_id}:{idempotency_key or uuid.uuid4()}"
    existing_result = await session.execute(
        select(OutboxEvent).where(OutboxEvent.idempotency_key == event_key)
    )
    if existing := existing_result.scalar_one_or_none():
        raw_version = existing.payload.get("version_id")
        return IngestionQueuedResponse(
            job_id=existing.id,
            course_id=course_id,
            version_id=UUID(raw_version) if raw_version else None,
        )

    event = OutboxEvent(
        id=uuid.uuid4(),
        topic="ingestion.scan",
        idempotency_key=event_key,
        payload={
            "tenant_id": str(principal.tenant_id),
            "course_id": str(course.id),
            "source_root_id": str(source_root.id),
            "course_run_id": str(course_run.id),
            "resolved_path": source_root.absolute_path,
            "pipeline_version": PIPELINE_VERSION,
            "trigger": "manual",
        },
        attempts=0,
    )
    session.add(event)
    _audit(
        session,
        principal,
        "ingestion.queue",
        "outbox_event",
        event.id,
        course_id=str(course_id),
    )
    await session.commit()
    return IngestionQueuedResponse(job_id=event.id, course_id=course.id)


@router.get("/ingestions/{job_id}", response_model=IngestionStatusResponse)
async def get_ingestion_status(
    job_id: UUID,
    session: Annotated[AsyncSession, Depends(get_session)],
    principal: Annotated[Principal, Depends(require_course_admin)],
) -> IngestionStatusResponse:
    event = await session.get(OutboxEvent, job_id)
    if (
        event is None
        or event.topic != "ingestion.scan"
        or event.payload.get("tenant_id") != str(principal.tenant_id)
    ):
        raise HTTPException(status_code=404, detail="ingestion job not found")
    raw_version = event.payload.get("version_id")
    version = await session.get(ContentVersion, UUID(raw_version)) if raw_version else None
    embedding_event = None
    if version is not None:
        embedding_result = await session.execute(
            select(OutboxEvent).where(OutboxEvent.idempotency_key == f"embed:{version.id}")
        )
        embedding_event = embedding_result.scalar_one_or_none()
    state = (
        "dead_lettered"
        if event.dead_lettered_at
        or (embedding_event is not None and embedding_event.dead_lettered_at is not None)
        else "processed"
        if event.processed_at
        else "pending"
    )
    failure_event = (
        embedding_event if embedding_event is not None and embedding_event.last_error else event
    )
    return IngestionStatusResponse(
        job_id=event.id,
        course_id=UUID(event.payload["course_id"]),
        version_id=version.id if version else None,
        status=state,
        version_status=version.status.value if version else None,
        attempts=failure_event.attempts,
        processed_at=event.processed_at,
        dead_lettered_at=(
            embedding_event.dead_lettered_at
            if embedding_event is not None and embedding_event.dead_lettered_at is not None
            else event.dead_lettered_at
        ),
        last_error=failure_event.last_error,
        stats=event.payload.get("stats", {}),
    )


@router.post("/ingestions/{job_id}/retry", response_model=IngestionQueuedResponse)
async def retry_ingestion(
    job_id: UUID,
    session: Annotated[AsyncSession, Depends(get_session)],
    principal: Annotated[Principal, Depends(require_course_admin)],
) -> IngestionQueuedResponse:
    event = await session.get(OutboxEvent, job_id)
    if (
        event is None
        or event.topic != "ingestion.scan"
        or event.payload.get("tenant_id") != str(principal.tenant_id)
    ):
        raise HTTPException(status_code=404, detail="ingestion job not found")
    retry_event = event
    if event.processed_at is not None:
        raw_version = event.payload.get("version_id")
        if not raw_version:
            raise HTTPException(status_code=409, detail="processed jobs cannot be retried")
        version = await session.get(ContentVersion, UUID(raw_version))
        embedding_result = await session.execute(
            select(OutboxEvent).where(OutboxEvent.idempotency_key == f"embed:{raw_version}")
        )
        embedding_event = embedding_result.scalar_one_or_none()
        if (
            version is None
            or embedding_event is None
            or embedding_event.processed_at is not None
            or embedding_event.dead_lettered_at is None
        ):
            raise HTTPException(status_code=409, detail="processed jobs cannot be retried")
        retry_event = embedding_event
        version.status = ContentVersionStatus.BUILDING
    retry_event.dead_lettered_at = None
    retry_event.last_error = None
    retry_event.attempts = 0
    _audit(
        session,
        principal,
        "ingestion.retry",
        "outbox_event",
        retry_event.id,
        root_job_id=str(event.id),
    )
    await session.commit()
    raw_version = event.payload.get("version_id")
    return IngestionQueuedResponse(
        job_id=event.id,
        course_id=UUID(event.payload["course_id"]),
        version_id=UUID(raw_version) if raw_version else None,
    )


@router.get("/courses/{course_id}/sources", response_model=list[SourceStatusResponse])
async def list_sources(
    course_id: UUID,
    session: Annotated[AsyncSession, Depends(get_session)],
    principal: Annotated[Principal, Depends(require_course_admin)],
    version_id: UUID | None = None,
) -> list[SourceStatusResponse]:
    course = await _tenant_course(session, course_id, principal)
    selected_version = version_id or course.active_content_version_id
    if selected_version is None:
        return []
    version = await session.get(ContentVersion, selected_version)
    if version is None or version.course_id != course.id:
        raise HTTPException(status_code=404, detail="content version not found")
    result = await session.execute(
        select(SourceDocument)
        .join(ContentVersionSource, ContentVersionSource.source_id == SourceDocument.id)
        .where(ContentVersionSource.version_id == selected_version)
        .order_by(SourceDocument.relative_path)
    )
    return [
        SourceStatusResponse(
            id=item.id,
            version_id=selected_version,
            relative_path=item.relative_path,
            checksum=item.checksum,
            extraction_status=item.extraction_status.value,
            failure_reason=item.failure_reason,
            artifact_key=item.artifact_key,
        )
        for item in result.scalars().all()
    ]


@router.get(
    "/courses/{course_id}/versions",
    response_model=list[ContentVersionSummaryResponse],
)
async def list_versions(
    course_id: UUID,
    session: Annotated[AsyncSession, Depends(get_session)],
    principal: Annotated[Principal, Depends(require_course_admin)],
) -> list[ContentVersionSummaryResponse]:
    course = await _tenant_course(session, course_id, principal)
    result = await session.execute(
        select(ContentVersion)
        .where(ContentVersion.course_id == course.id)
        .order_by(ContentVersion.sequence.desc())
    )
    return [
        ContentVersionSummaryResponse(
            version_id=item.id,
            sequence=item.sequence,
            status=item.status.value,
            source_snapshot_hash=item.source_snapshot_hash,
            embedding_model_version=item.embedding_model_version,
            embedding_dimension=item.embedding_dimension,
            published_at=item.published_at,
        )
        for item in result.scalars().all()
    ]


@router.post(
    "/courses/{course_id}/versions/{version_id}/publish",
    response_model=VersionActionResponse,
)
async def publish_version(
    course_id: UUID,
    version_id: UUID,
    session: Annotated[AsyncSession, Depends(get_session)],
    principal: Annotated[Principal, Depends(require_course_admin)],
) -> VersionActionResponse:
    course = await _tenant_course(session, course_id, principal)
    version = await session.get(ContentVersion, version_id)
    if version is None or version.course_id != course.id:
        raise HTTPException(status_code=404, detail="version not found")
    if version.status != ContentVersionStatus.READY:
        raise HTTPException(status_code=409, detail="only READY versions can be published")
    now = datetime.now(UTC).replace(tzinfo=None)
    version.status = ContentVersionStatus.PUBLISHED
    version.published_at = now
    course.active_content_version_id = version.id
    run_result = await session.execute(
        select(CourseRun).where(CourseRun.id == version.course_run_id)
    )
    if course_run := run_result.scalar_one_or_none():
        course_run.active_content_version_id = version.id
    _audit(session, principal, "version.publish", "content_version", version.id)
    await session.commit()
    record_content_version_operation("agent-api", "publish")
    return VersionActionResponse(
        version_id=version.id,
        active_version_id=version.id,
        status=version.status.value,
        published_at=version.published_at,
    )


@router.post(
    "/courses/{course_id}/versions/{version_id}/rollback",
    response_model=VersionActionResponse,
)
async def rollback_version(
    course_id: UUID,
    version_id: UUID,
    session: Annotated[AsyncSession, Depends(get_session)],
    principal: Annotated[Principal, Depends(require_course_admin)],
) -> VersionActionResponse:
    course = await _tenant_course(session, course_id, principal)
    if course.active_content_version_id != version_id:
        raise HTTPException(status_code=409, detail="only the active version can be rolled back")
    current = await session.get(ContentVersion, version_id)
    result = await session.execute(
        select(ContentVersion)
        .where(
            ContentVersion.course_id == course.id,
            ContentVersion.id != version_id,
            ContentVersion.status == ContentVersionStatus.PUBLISHED,
        )
        .order_by(ContentVersion.published_at.desc(), ContentVersion.sequence.desc())
        .limit(1)
    )
    previous = result.scalar_one_or_none()
    if current is None or previous is None:
        raise HTTPException(status_code=409, detail="no previous published version exists")
    current.status = ContentVersionStatus.ROLLED_BACK
    course.active_content_version_id = previous.id
    run = await session.get(CourseRun, current.course_run_id)
    if run is not None:
        run.active_content_version_id = previous.id
    _audit(
        session,
        principal,
        "version.rollback",
        "content_version",
        current.id,
        restored_version_id=str(previous.id),
    )
    await session.commit()
    record_content_version_operation("agent-api", "rollback")
    return VersionActionResponse(
        version_id=current.id,
        active_version_id=previous.id,
        status=current.status.value,
        published_at=previous.published_at,
    )
