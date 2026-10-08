"""Versioned catalog transport contracts shared by Agent and Hiruzen."""

from __future__ import annotations

from datetime import datetime
from typing import Literal
from uuid import UUID

from pydantic import BaseModel, ConfigDict, Field

from course_tutor_contracts.enums import (
    BookLifecycleStatus,
    CatalogCandidateStatus,
    CatalogImportStatus,
    CategoryType,
    EducationLevel,
)


class CatalogModel(BaseModel):
    model_config = ConfigDict(extra="forbid", frozen=True)


class CatalogCategoryView(CatalogModel):
    id: UUID
    stable_key: str
    display_name: str
    category_type: CategoryType
    parent_id: UUID | None = None
    book_count: int = Field(ge=0)


class CatalogCourseView(CatalogModel):
    course_id: UUID
    course_run_id: UUID
    code: str
    name: str
    content_version_id: UUID
    access_policy: Literal["tenant_authenticated"] = "tenant_authenticated"


class CatalogBookSummary(CatalogModel):
    id: UUID
    title: str
    education_level: EducationLevel
    subject: str
    grade: str
    publisher: str
    series: str
    edition: str | None = None
    start_grade: str | None = None
    editor: str | None = None
    term: str
    language: str
    isbn: str | None = None
    cover_uri: str | None = None
    lifecycle_status: BookLifecycleStatus


class CatalogBookDetail(CatalogBookSummary):
    courses: tuple[CatalogCourseView, ...] = ()


class CatalogBookPage(CatalogModel):
    items: tuple[CatalogBookSummary, ...]
    next_cursor: str | None = None


class CatalogImportCreateRequest(BaseModel):
    source_root_id: UUID
    prefix: str = Field(default=".", min_length=1, max_length=512)
    series_contains: str | None = Field(default=None, min_length=1, max_length=255)

    model_config = ConfigDict(extra="forbid")


class CatalogImportJob(CatalogModel):
    import_id: UUID
    batch_id: UUID | None = None
    status: Literal["queued", "staged", "failed"]
    candidate_count: int = Field(default=0, ge=0)
    needs_review_count: int = Field(default=0, ge=0)
    failure_reason: str | None = None


class CatalogImportCandidateView(CatalogModel):
    id: UUID
    stable_key: str
    checksum: str
    size_bytes: int = Field(ge=0)
    metadata: dict[str, object]
    status: CatalogCandidateStatus
    issues: tuple[str, ...] = ()
    imported_book_id: UUID | None = None


class CatalogCandidateUpdateRequest(BaseModel):
    metadata: dict[str, str | None]

    model_config = ConfigDict(extra="forbid")


class CatalogApprovalResult(CatalogModel):
    candidate_id: UUID
    book_id: UUID
    course_id: UUID
    course_run_id: UUID
    ingestion_job_id: UUID
    status: CatalogCandidateStatus = CatalogCandidateStatus.IMPORTED


class CatalogBatchApprovalResult(CatalogModel):
    approved: tuple[CatalogApprovalResult, ...]


class CatalogImportBatchView(CatalogModel):
    id: UUID
    status: CatalogImportStatus
    candidate_count: int
    needs_review_count: int
    completed_at: datetime | None = None
