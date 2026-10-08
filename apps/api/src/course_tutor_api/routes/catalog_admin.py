"""Admin catalog scan, review and activation workflow."""

from __future__ import annotations

import hashlib
import json
import unicodedata
import uuid
from typing import Annotated, Any, Literal
from uuid import UUID

from fastapi import APIRouter, Depends, Header, HTTPException, status
from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession

from course_tutor_api.auth import Principal, get_current_principal, require_course_admin
from course_tutor_api.db import (
    AuditEvent,
    Book,
    BookCourseBinding,
    CatalogImportBatch,
    CatalogImportCandidate,
    Category,
    Course,
    CourseRun,
    OutboxEvent,
    Programme,
    Publisher,
    SourceRoot,
)
from course_tutor_api.dependencies import (
    Dependencies,
    RedisRateLimiter,
    dependencies_from_request,
    get_session,
)
from course_tutor_contracts import (
    BookLifecycleStatus,
    CatalogApprovalResult,
    CatalogBatchApprovalResult,
    CatalogCandidateStatus,
    CatalogCandidateUpdateRequest,
    CatalogImportCandidateView,
    CatalogImportCreateRequest,
    CatalogImportJob,
    CategoryType,
    CourseAccessPolicy,
    EducationLevel,
)
from course_tutor_shared import PIPELINE_VERSION, get_correlation_id


async def _enforce_rate_limit(
    principal: Annotated[Principal, Depends(get_current_principal)],
    dependencies: Annotated[Dependencies, Depends(dependencies_from_request)],
) -> None:
    await RedisRateLimiter(dependencies.redis).enforce(
        f"catalog-admin:{principal.tenant_id}:{principal.user_id}",
        limit=120,
        window_seconds=60,
    )


router = APIRouter(
    prefix="/v1/admin/catalog",
    tags=["catalog-admin"],
    dependencies=[Depends(_enforce_rate_limit)],
)

_EDITABLE_METADATA = {
    "education_level",
    "education_level_display",
    "subject",
    "publisher",
    "series",
    "edition",
    "start_grade",
    "editor",
    "grade",
    "term",
    "title",
    "normalized_title",
    "language",
    "isbn",
    "cover_uri",
}
_REQUIRED_METADATA = {
    "education_level",
    "subject",
    "publisher",
    "series",
    "grade",
    "term",
    "title",
    "language",
}


def _normalize(value: str) -> str:
    return " ".join(unicodedata.normalize("NFKC", value).strip().split()).casefold()


def _stable_key(metadata: dict[str, Any]) -> str:
    fields = (
        "education_level",
        "subject",
        "publisher",
        "series",
        "start_grade",
        "editor",
        "grade",
        "term",
        "title",
    )
    canonical = {field: _normalize(str(metadata.get(field) or "")) for field in fields}
    encoded = json.dumps(canonical, ensure_ascii=False, sort_keys=True).encode()
    return f"china-textbook:{hashlib.sha256(encoded).hexdigest()[:32]}"


def _audit(
    session: AsyncSession,
    principal: Principal,
    action: str,
    resource_type: str,
    resource_id: UUID,
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


def _candidate_view(candidate: CatalogImportCandidate) -> CatalogImportCandidateView:
    return CatalogImportCandidateView(
        id=candidate.id,
        stable_key=candidate.stable_key,
        checksum=candidate.checksum,
        size_bytes=candidate.size_bytes,
        metadata=dict(candidate.metadata_),
        status=candidate.status,
        issues=tuple(candidate.issues),
        imported_book_id=candidate.imported_book_id,
    )


async def _import_event(
    session: AsyncSession, import_id: UUID, principal: Principal
) -> OutboxEvent:
    event = await session.get(OutboxEvent, import_id)
    if (
        event is None
        or event.topic != "catalog.scan"
        or event.payload.get("tenant_id") != str(principal.tenant_id)
    ):
        raise HTTPException(
            status_code=status.HTTP_404_NOT_FOUND,
            detail="catalog import not found",
        )
    return event


async def _event_batch(
    session: AsyncSession, event: OutboxEvent, *, required: bool = True
) -> CatalogImportBatch | None:
    raw_batch_id = event.payload.get("batch_id")
    if raw_batch_id is None:
        if required:
            raise HTTPException(
                status_code=status.HTTP_409_CONFLICT,
                detail="catalog import scan has not completed",
            )
        return None
    batch = await session.get(CatalogImportBatch, UUID(raw_batch_id))
    if batch is None:
        raise HTTPException(status_code=409, detail="catalog import batch is unavailable")
    return batch


@router.post(
    "/imports",
    response_model=CatalogImportJob,
    status_code=status.HTTP_202_ACCEPTED,
    operation_id="createCatalogImport",
)
async def create_catalog_import(
    body: CatalogImportCreateRequest,
    session: Annotated[AsyncSession, Depends(get_session)],
    principal: Annotated[Principal, Depends(require_course_admin)],
    idempotency_key: Annotated[str | None, Header(alias="Idempotency-Key")] = None,
) -> CatalogImportJob:
    source_root = await session.get(SourceRoot, body.source_root_id)
    if source_root is None or source_root.tenant_id != principal.tenant_id:
        raise HTTPException(status_code=404, detail="source root not found")
    selection = {
        "prefix": body.prefix,
        **({"series_contains": body.series_contains} if body.series_contains else {}),
    }
    event_key = (
        f"catalog-scan:{principal.tenant_id}:{body.source_root_id}:"
        f"{idempotency_key or uuid.uuid4()}"
    )
    existing = await session.scalar(
        select(OutboxEvent).where(OutboxEvent.idempotency_key == event_key)
    )
    if existing is not None:
        return await _job_view(session, existing)
    event = OutboxEvent(
        id=uuid.uuid4(),
        topic="catalog.scan",
        idempotency_key=event_key,
        payload={
            "tenant_id": str(principal.tenant_id),
            "source_root_id": str(source_root.id),
            "selection": selection,
            **selection,
        },
        correlation_id=get_correlation_id(),
        attempts=0,
    )
    session.add(event)
    _audit(session, principal, "catalog.import.queue", "outbox_event", event.id)
    await session.commit()
    return CatalogImportJob(import_id=event.id, status="queued")


async def _job_view(session: AsyncSession, event: OutboxEvent) -> CatalogImportJob:
    batch = await _event_batch(session, event, required=False)
    state: Literal["queued", "staged", "failed"]
    if event.dead_lettered_at is not None:
        state = "failed"
    elif batch is not None:
        state = "staged"
    else:
        state = "queued"
    return CatalogImportJob(
        import_id=event.id,
        batch_id=batch.id if batch else None,
        status=state,
        candidate_count=batch.candidate_count if batch else 0,
        needs_review_count=batch.needs_review_count if batch else 0,
        failure_reason="catalog scan failed" if state == "failed" else None,
    )


@router.get(
    "/imports/{import_id}",
    response_model=CatalogImportJob,
    operation_id="getCatalogImport",
)
async def get_catalog_import(
    import_id: UUID,
    session: Annotated[AsyncSession, Depends(get_session)],
    principal: Annotated[Principal, Depends(require_course_admin)],
) -> CatalogImportJob:
    return await _job_view(session, await _import_event(session, import_id, principal))


@router.get(
    "/imports/{import_id}/candidates",
    response_model=list[CatalogImportCandidateView],
    operation_id="listCatalogImportCandidates",
)
async def list_catalog_import_candidates(
    import_id: UUID,
    session: Annotated[AsyncSession, Depends(get_session)],
    principal: Annotated[Principal, Depends(require_course_admin)],
) -> list[CatalogImportCandidateView]:
    batch = await _event_batch(session, await _import_event(session, import_id, principal))
    assert batch is not None
    result = await session.execute(
        select(CatalogImportCandidate)
        .where(CatalogImportCandidate.batch_id == batch.id)
        .order_by(CatalogImportCandidate.stable_key, CatalogImportCandidate.id)
    )
    return [_candidate_view(candidate) for candidate in result.scalars().all()]


async def _candidate_for_import(
    session: AsyncSession,
    import_id: UUID,
    candidate_id: UUID,
    principal: Principal,
) -> tuple[CatalogImportBatch, CatalogImportCandidate]:
    batch = await _event_batch(session, await _import_event(session, import_id, principal))
    assert batch is not None
    candidate = await session.get(CatalogImportCandidate, candidate_id)
    if candidate is None or candidate.batch_id != batch.id:
        raise HTTPException(status_code=404, detail="catalog candidate not found")
    return batch, candidate


@router.patch(
    "/imports/{import_id}/candidates/{candidate_id}",
    response_model=CatalogImportCandidateView,
    operation_id="updateCatalogImportCandidate",
)
async def update_catalog_import_candidate(
    import_id: UUID,
    candidate_id: UUID,
    body: CatalogCandidateUpdateRequest,
    session: Annotated[AsyncSession, Depends(get_session)],
    principal: Annotated[Principal, Depends(require_course_admin)],
) -> CatalogImportCandidateView:
    _, candidate = await _candidate_for_import(session, import_id, candidate_id, principal)
    if candidate.status in {CatalogCandidateStatus.IMPORTED, CatalogCandidateStatus.REJECTED}:
        raise HTTPException(status_code=409, detail="catalog candidate is immutable")
    unknown = set(body.metadata) - _EDITABLE_METADATA
    if unknown:
        raise HTTPException(status_code=422, detail=f"unknown metadata fields: {sorted(unknown)}")
    metadata = {**candidate.metadata_, **body.metadata}
    missing = sorted(field for field in _REQUIRED_METADATA if not metadata.get(field))
    if missing:
        raise HTTPException(status_code=422, detail=f"missing metadata fields: {missing}")
    try:
        EducationLevel(str(metadata["education_level"]))
    except ValueError as exc:
        raise HTTPException(status_code=422, detail="invalid education_level") from exc
    metadata["normalized_title"] = _normalize(str(metadata["title"]))
    candidate.metadata_ = metadata
    candidate.stable_key = _stable_key(metadata)
    candidate.issues = []
    candidate.status = CatalogCandidateStatus.STAGED
    _audit(session, principal, "catalog.candidate.update", "catalog_candidate", candidate.id)
    await session.commit()
    return _candidate_view(candidate)


async def _ensure_category(
    session: AsyncSession,
    *,
    tenant_id: UUID,
    stable_key: str,
    display_name: str,
    category_type: CategoryType,
    parent_id: UUID | None = None,
) -> Category:
    category = await session.scalar(
        select(Category).where(
            Category.tenant_id == tenant_id,
            Category.stable_key == stable_key,
        )
    )
    if category is None:
        category = Category(
            id=uuid.uuid4(),
            tenant_id=tenant_id,
            stable_key=stable_key,
            display_name=display_name,
            category_type=category_type,
            parent_id=parent_id,
        )
        session.add(category)
        await session.flush()
    return category


async def _activate_candidate(
    session: AsyncSession,
    principal: Principal,
    batch: CatalogImportBatch,
    candidate: CatalogImportCandidate,
) -> CatalogApprovalResult:
    if candidate.status is CatalogCandidateStatus.NEEDS_REVIEW or candidate.issues:
        raise HTTPException(status_code=409, detail="candidate metadata requires review")
    if candidate.status is CatalogCandidateStatus.REJECTED:
        raise HTTPException(status_code=409, detail="rejected candidate cannot be approved")
    metadata = dict(candidate.metadata_)
    missing = sorted(field for field in _REQUIRED_METADATA if not metadata.get(field))
    if missing:
        raise HTTPException(status_code=409, detail=f"candidate metadata is incomplete: {missing}")

    publisher_name = str(metadata["publisher"])
    normalized_publisher = _normalize(publisher_name)
    publisher = await session.scalar(
        select(Publisher).where(
            Publisher.tenant_id == principal.tenant_id,
            Publisher.normalized_name == normalized_publisher,
        )
    )
    if publisher is None:
        publisher = Publisher(
            id=uuid.uuid4(),
            tenant_id=principal.tenant_id,
            stable_key=f"publisher:{normalized_publisher}",
            display_name=publisher_name,
            normalized_name=normalized_publisher,
            aliases=[],
        )
        session.add(publisher)
        await session.flush()

    level = EducationLevel(str(metadata["education_level"]))
    level_category = await _ensure_category(
        session,
        tenant_id=principal.tenant_id,
        stable_key=f"education:{level.value}",
        display_name=str(metadata.get("education_level_display") or level.value),
        category_type=CategoryType.EDUCATION_LEVEL,
    )
    subject_category = await _ensure_category(
        session,
        tenant_id=principal.tenant_id,
        stable_key=f"subject:{level.value}:{metadata['subject']}",
        display_name=str(metadata["subject"]),
        category_type=CategoryType.SUBJECT,
        parent_id=level_category.id,
    )
    await _ensure_category(
        session,
        tenant_id=principal.tenant_id,
        stable_key=f"grade:{level.value}:{metadata['subject']}:{metadata['grade']}",
        display_name=str(metadata["grade"]),
        category_type=CategoryType.GRADE,
        parent_id=subject_category.id,
    )
    await _ensure_category(
        session,
        tenant_id=principal.tenant_id,
        stable_key=f"publisher:{normalized_publisher}",
        display_name=publisher_name,
        category_type=CategoryType.PUBLISHER,
    )

    book = await session.scalar(
        select(Book).where(
            Book.tenant_id == principal.tenant_id,
            Book.stable_key == candidate.stable_key,
        )
    )
    if book is None:
        book = Book(
            id=uuid.uuid4(),
            tenant_id=principal.tenant_id,
            stable_key=candidate.stable_key,
            title=str(metadata["title"]),
            normalized_title=_normalize(str(metadata["title"])),
            education_level=level,
            subject=str(metadata["subject"]),
            grade=str(metadata["grade"]),
            publisher_id=publisher.id,
            series=str(metadata["series"]),
            edition=str(metadata["edition"]) if metadata.get("edition") else None,
            start_grade=str(metadata["start_grade"]) if metadata.get("start_grade") else None,
            editor=str(metadata["editor"]) if metadata.get("editor") else None,
            term=str(metadata["term"]),
            language=str(metadata["language"]),
            isbn=str(metadata["isbn"]) if metadata.get("isbn") else None,
            cover_uri=str(metadata["cover_uri"]) if metadata.get("cover_uri") else None,
            lifecycle_status=BookLifecycleStatus.DRAFT,
        )
        session.add(book)
        await session.flush()

    binding_result = await session.execute(
        select(Course, CourseRun)
        .join(CourseRun, CourseRun.course_id == Course.id)
        .join(BookCourseBinding, BookCourseBinding.course_run_id == CourseRun.id)
        .where(BookCourseBinding.book_id == book.id)
        .limit(1)
    )
    binding = binding_result.one_or_none()
    source_root = await session.get(SourceRoot, batch.source_root_id)
    if source_root is None or source_root.tenant_id != principal.tenant_id:
        raise HTTPException(status_code=409, detail="catalog source root is unavailable")
    if binding is None:
        programme = await session.scalar(
            select(Programme).where(
                Programme.tenant_id == principal.tenant_id,
                Programme.code == "CHINA-TEXTBOOK",
            )
        )
        if programme is None:
            programme = Programme(
                id=uuid.uuid4(),
                tenant_id=principal.tenant_id,
                code="CHINA-TEXTBOOK",
                name="ChinaTextbook System Catalog",
            )
            session.add(programme)
            await session.flush()
        course_root = SourceRoot(
            id=uuid.uuid4(),
            tenant_id=principal.tenant_id,
            absolute_path=source_root.absolute_path,
            last_scanned_at=None,
            last_snapshot_hash=None,
            scan_interval_seconds=source_root.scan_interval_seconds,
            automatic_ingestion_enabled=False,
        )
        session.add(course_root)
        await session.flush()
        course = Course(
            id=uuid.uuid4(),
            tenant_id=principal.tenant_id,
            programme_id=programme.id,
            code=f"TXT-{candidate.stable_key.rsplit(':', 1)[-1][:24].upper()}",
            name=book.title,
            level=book.education_level,
            source_root_id=course_root.id,
            teaching_policy={},
        )
        session.add(course)
        await session.flush()
        course_run = CourseRun(
            id=uuid.uuid4(),
            course_id=course.id,
            run_key="system",
            source_root_id=course_root.id,
            active_content_version_id=None,
            access_policy=CourseAccessPolicy.TENANT_AUTHENTICATED,
        )
        session.add(course_run)
        await session.flush()
        session.add(BookCourseBinding(book_id=book.id, course_run_id=course_run.id))
    else:
        course, course_run = binding
        existing_course_root = await session.get(SourceRoot, course_run.source_root_id)
        if existing_course_root is None:
            raise HTTPException(status_code=409, detail="book course source root is unavailable")
        course_root = existing_course_root

    event_key = f"catalog-book:{book.id}:{candidate.checksum}"
    ingestion = await session.scalar(
        select(OutboxEvent).where(OutboxEvent.idempotency_key == event_key)
    )
    if ingestion is None:
        ingestion = OutboxEvent(
            id=uuid.uuid4(),
            topic="ingestion.scan",
            idempotency_key=event_key,
            payload={
                "tenant_id": str(principal.tenant_id),
                "course_id": str(course.id),
                "source_root_id": str(course_root.id),
                "course_run_id": str(course_run.id),
                "resolved_path": course_root.absolute_path,
                "include_relative_paths": [candidate.relative_path],
                "pipeline_version": PIPELINE_VERSION,
                "trigger": "catalog_approval",
                "book_id": str(book.id),
            },
            correlation_id=get_correlation_id(),
            attempts=0,
        )
        session.add(ingestion)
    candidate.imported_book_id = book.id
    candidate.status = CatalogCandidateStatus.IMPORTED
    _audit(
        session,
        principal,
        "catalog.candidate.approve",
        "catalog_candidate",
        candidate.id,
        book_id=str(book.id),
        course_id=str(course.id),
    )
    return CatalogApprovalResult(
        candidate_id=candidate.id,
        book_id=book.id,
        course_id=course.id,
        course_run_id=course_run.id,
        ingestion_job_id=ingestion.id,
    )


@router.post(
    "/imports/{import_id}/candidates/{candidate_id}/approve",
    response_model=CatalogApprovalResult,
    status_code=status.HTTP_202_ACCEPTED,
    operation_id="approveCatalogImportCandidate",
)
async def approve_catalog_import_candidate(
    import_id: UUID,
    candidate_id: UUID,
    session: Annotated[AsyncSession, Depends(get_session)],
    principal: Annotated[Principal, Depends(require_course_admin)],
) -> CatalogApprovalResult:
    batch, candidate = await _candidate_for_import(session, import_id, candidate_id, principal)
    result = await _activate_candidate(session, principal, batch, candidate)
    await session.commit()
    return result


@router.post(
    "/imports/{import_id}/approve",
    response_model=CatalogBatchApprovalResult,
    status_code=status.HTTP_202_ACCEPTED,
    operation_id="approveCatalogImportCandidates",
)
async def approve_catalog_import_candidates(
    import_id: UUID,
    session: Annotated[AsyncSession, Depends(get_session)],
    principal: Annotated[Principal, Depends(require_course_admin)],
) -> CatalogBatchApprovalResult:
    batch = await _event_batch(session, await _import_event(session, import_id, principal))
    assert batch is not None
    candidates = (
        (
            await session.execute(
                select(CatalogImportCandidate)
                .where(
                    CatalogImportCandidate.batch_id == batch.id,
                    CatalogImportCandidate.status == CatalogCandidateStatus.STAGED,
                )
                .order_by(CatalogImportCandidate.stable_key, CatalogImportCandidate.id)
            )
        )
        .scalars()
        .all()
    )
    approved = tuple(
        [
            await _activate_candidate(session, principal, batch, candidate)
            for candidate in candidates
        ]
    )
    await session.commit()
    return CatalogBatchApprovalResult(approved=approved)


@router.post(
    "/imports/{import_id}/candidates/{candidate_id}/reject",
    response_model=CatalogImportCandidateView,
    operation_id="rejectCatalogImportCandidate",
)
async def reject_catalog_import_candidate(
    import_id: UUID,
    candidate_id: UUID,
    session: Annotated[AsyncSession, Depends(get_session)],
    principal: Annotated[Principal, Depends(require_course_admin)],
) -> CatalogImportCandidateView:
    _, candidate = await _candidate_for_import(session, import_id, candidate_id, principal)
    if candidate.status is CatalogCandidateStatus.IMPORTED:
        raise HTTPException(status_code=409, detail="imported candidate cannot be rejected")
    candidate.status = CatalogCandidateStatus.REJECTED
    _audit(session, principal, "catalog.candidate.reject", "catalog_candidate", candidate.id)
    await session.commit()
    return _candidate_view(candidate)
