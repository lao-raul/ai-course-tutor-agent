"""Delegated, version-pinned evidence for asynchronous ChinaTextbook practice."""

from __future__ import annotations

from typing import Annotated

import jwt
from fastapi import APIRouter, Depends, Header, HTTPException
from pydantic import ValidationError
from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession

from course_tutor_api.db import (
    Book,
    BookContentBinding,
    BookOutline,
    ContentVersion,
    Course,
    CourseRun,
    SourceDocument,
)
from course_tutor_api.dependencies import Dependencies, dependencies_from_request, get_session
from course_tutor_api.routes.chat import (
    _build_evidence_pack,
    _create_trace,
    _get_reranker,
    _get_retrieval_service,
)
from course_tutor_auth.practice_delegation import verify_practice_delegation
from course_tutor_contracts import (
    BookLifecycleStatus,
    CatalogOutlineNode,
    ChunkClass,
    ContentVersionStatus,
    CourseAccessPolicy,
    PracticeEvidenceChunk,
    PracticeEvidenceRequest,
    PracticeEvidenceResponse,
)

router = APIRouter(prefix="/v1/internal/practice", tags=["practice-evidence"])
ALLOWED_CLASSES = (ChunkClass.CONTENT,)


def _outline_page_range(
    nodes: list[dict[str, object]], node_id: str, page_count: int
) -> tuple[int, int] | None:
    try:
        ordered = sorted(
            (CatalogOutlineNode.model_validate(item) for item in nodes),
            key=lambda item: item.ordinal,
        )
    except ValidationError:
        return None
    for index, node in enumerate(ordered):
        if node.id != node_id:
            continue
        start = node.page_start
        end = node.page_end if node.page_end is not None else page_count
        depth = node.depth
        for following in ordered[index + 1 :]:
            if following.depth <= depth and following.page_start > start:
                end = min(end, following.page_start - 1)
                break
        return (start, end) if 1 <= start <= end <= page_count else None
    return None


@router.post(
    "/evidence:retrieve",
    response_model=PracticeEvidenceResponse,
    operation_id="retrievePracticeEvidence",
)
async def retrieve_practice_evidence(
    body: PracticeEvidenceRequest,
    session: Annotated[AsyncSession, Depends(get_session)],
    deps: Annotated[Dependencies, Depends(dependencies_from_request)],
    authorization: Annotated[str | None, Header()] = None,
) -> PracticeEvidenceResponse:
    try:
        scheme, token = (authorization or "").split(" ", 1)
        if scheme.lower() != "bearer":
            raise jwt.InvalidTokenError("bearer required")
        delegation = verify_practice_delegation(
            token, deps.settings.practice_delegation_secret.get_secret_value()
        )
    except (ValueError, jwt.PyJWTError, ValidationError) as exc:
        raise HTTPException(status_code=401, detail="invalid practice delegation") from exc

    if (
        delegation.generation_id != body.generation_id
        or delegation.book_id != body.book_id
        or delegation.course_id != body.course_id
        or delegation.content_version_id != body.content_version_id
    ):
        raise HTTPException(status_code=403, detail="delegation scope mismatch")

    # Recheck the current Agent-owned catalog binding and active publication. The
    # first release accepts tenant-authenticated ChinaTextbook runs only; a stale,
    # unpublished or cross-tenant job has the same externally visible result.
    source_ids = tuple(
        (
            await session.scalars(
                select(BookContentBinding.source_id)
                .join(Book, Book.id == BookContentBinding.book_id)
                .join(CourseRun, CourseRun.id == BookContentBinding.course_run_id)
                .join(Course, Course.id == CourseRun.course_id)
                .join(ContentVersion, ContentVersion.id == BookContentBinding.content_version_id)
                .where(
                    Book.id == body.book_id,
                    Book.tenant_id == delegation.tenant_id,
                    Book.lifecycle_status == BookLifecycleStatus.PUBLISHED,
                    Course.id == body.course_id,
                    Course.tenant_id == delegation.tenant_id,
                    CourseRun.access_policy == CourseAccessPolicy.TENANT_AUTHENTICATED,
                    CourseRun.active_content_version_id == body.content_version_id,
                    Course.active_content_version_id == body.content_version_id,
                    ContentVersion.id == body.content_version_id,
                    ContentVersion.course_id == body.course_id,
                    ContentVersion.course_run_id == CourseRun.id,
                    ContentVersion.status == ContentVersionStatus.PUBLISHED,
                )
            )
        ).all()
    )
    if not source_ids:
        raise HTTPException(status_code=404, detail="published textbook evidence not found")

    page_range = None
    if body.outline_node_id is not None:
        outline = await session.scalar(
            select(BookOutline).where(
                BookOutline.book_id == body.book_id,
                BookOutline.content_version_id == body.content_version_id,
                BookOutline.availability == "available",
            )
        )
        if outline is None or outline.source_id not in source_ids:
            raise HTTPException(status_code=422, detail="selected textbook section unavailable")
        source = await session.get(SourceDocument, outline.source_id)
        page_count = (source.source_metadata or {}).get("page_count") if source else None
        if not isinstance(page_count, int) or page_count < 1:
            raise HTTPException(status_code=422, detail="selected textbook pages unavailable")
        page_range = _outline_page_range(outline.nodes, body.outline_node_id, page_count)
        if page_range is None:
            raise HTTPException(status_code=422, detail="selected textbook section unavailable")
        source_ids = (outline.source_id,)

    pack = await _build_evidence_pack(
        retrieval_service=_get_retrieval_service(deps),
        reranker=_get_reranker(),
        tenant_id=delegation.tenant_id,
        course_id=body.course_id,
        version_id=body.content_version_id,
        access_label=delegation.access_label,
        query=body.query,
        source_ids=source_ids,
        **({"page_range": page_range} if page_range is not None else {}),
        service_name=deps.settings.service_name,
    )
    allowed = tuple(chunk for chunk in pack.evidence if chunk.chunk_class in ALLOWED_CLASSES)[
        : body.limit
    ]
    trace_id = await _create_trace(
        session,
        deps,
        body.course_id,
        body.content_version_id,
        body.query,
        pack,
        stream_state="practice_evidence" if allowed else "practice_evidence_empty",
    )
    return PracticeEvidenceResponse(
        generation_id=body.generation_id,
        book_id=body.book_id,
        course_id=body.course_id,
        content_version_id=body.content_version_id,
        retrieval_trace_id=trace_id,
        retrieval_policy_version="typed-scope-dense-lexical-rescore-v2",
        allowed_content_classes=ALLOWED_CLASSES,
        solution_release_after_incorrect_attempts=3,
        chunks=tuple(
            PracticeEvidenceChunk(
                chunk_id=chunk.chunk_id,
                source_id=chunk.source_id,
                text=chunk.text,
                relative_path=chunk.relative_path,
                anchor_type=chunk.anchor_type,
                anchor_value=chunk.anchor_value,
                chunk_class=chunk.chunk_class,
                score=chunk.score,
            )
            for chunk in allowed
        ),
    )
