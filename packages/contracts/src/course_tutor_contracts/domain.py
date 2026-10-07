"""Core domain entities (design-spec §3).

These are the transport/DTO shapes. Persistence models live in ``course_tutor_api.db``
and are kept structurally aligned by the schema tests.
"""

from __future__ import annotations

from datetime import datetime
from uuid import UUID

from pydantic import BaseModel, ConfigDict, Field

from course_tutor_contracts.enums import (
    AccessLabel,
    AnchorType,
    BookLifecycleStatus,
    CatalogCandidateStatus,
    CategoryType,
    ChunkClass,
    ContentVersionStatus,
    EducationLevel,
    ExtractionStatus,
    MemoryFactStatus,
    MemoryFactType,
)


class DomainModel(BaseModel):
    """Strict base: unknown fields are an error, not silently dropped."""

    model_config = ConfigDict(extra="forbid", frozen=True, from_attributes=True)


class Course(DomainModel):
    id: UUID
    tenant_id: UUID
    programme_id: UUID
    code: str
    name: str
    level: EducationLevel
    active_content_version: UUID | None = None
    source_root_id: UUID | None = None


class Category(DomainModel):
    id: UUID
    tenant_id: UUID
    stable_key: str
    display_name: str
    category_type: CategoryType
    parent_id: UUID | None = None


class Publisher(DomainModel):
    id: UUID
    tenant_id: UUID
    stable_key: str
    display_name: str
    normalized_name: str
    aliases: tuple[str, ...] = ()


class Book(DomainModel):
    id: UUID
    tenant_id: UUID
    stable_key: str
    title: str
    normalized_title: str
    education_level: EducationLevel
    subject: str
    grade: str
    publisher_id: UUID
    series: str
    edition: str | None = None
    start_grade: str | None = None
    editor: str | None = None
    term: str
    language: str
    isbn: str | None = None
    cover_uri: str | None = None
    lifecycle_status: BookLifecycleStatus = BookLifecycleStatus.DRAFT


class CatalogImportCandidate(DomainModel):
    id: UUID
    batch_id: UUID
    stable_key: str
    relative_path: str
    checksum: str
    size_bytes: int = Field(ge=0)
    metadata: dict[str, object]
    status: CatalogCandidateStatus
    issues: tuple[str, ...] = ()
    imported_book_id: UUID | None = None


class ContentVersion(DomainModel):
    id: UUID
    course_id: UUID
    course_run_id: UUID
    pipeline_version: str
    status: ContentVersionStatus
    created_at: datetime
    published_at: datetime | None = None


class SourceDocument(DomainModel):
    id: UUID
    version_id: UUID
    relative_path: str
    checksum: str
    mime_type: str
    access_label: AccessLabel
    extraction_status: ExtractionStatus
    extraction_confidence: float | None = Field(default=None, ge=0.0, le=1.0)
    failure_reason: str | None = None


class Chunk(DomainModel):
    id: UUID
    source_id: UUID
    ordinal: int = Field(ge=0)
    text: str
    anchor_type: AnchorType
    anchor_value: str
    chunk_class: ChunkClass = ChunkClass.CONTENT
    embedding_model_version: str


class ChatSession(DomainModel):
    id: UUID
    user_id: UUID
    course_id: UUID
    rolling_summary: str | None = None
    created_at: datetime
    expires_at: datetime | None = None


class ChatTurn(DomainModel):
    id: UUID
    session_id: UUID
    role: str
    content: str
    token_count: int = Field(ge=0)
    created_at: datetime


class MemoryFact(DomainModel):
    """An atomic, typed learner fact. Never a free-form blob (design-spec §5)."""

    id: UUID
    user_id: UUID
    course_id: UUID | None = None
    type: MemoryFactType
    normalized_value: str
    confidence: float = Field(ge=0.0, le=1.0)
    importance: float = Field(ge=0.0, le=1.0)
    evidence_ids: tuple[UUID, ...] = ()
    status: MemoryFactStatus = MemoryFactStatus.ACTIVE
    pinned: bool = False
    created_at: datetime
    last_confirmed_at: datetime | None = None
    expires_at: datetime | None = None
    supersedes_id: UUID | None = None


class RetrievalTrace(DomainModel):
    """Recorded per request so emitted citations can be validated server-side
    against what retrieval actually returned (design-spec §4.5)."""

    id: UUID
    request_id: str
    query: str
    candidate_ids: tuple[UUID, ...]
    reranked_ids: tuple[UUID, ...]
    scores: tuple[float, ...]
    content_version: UUID
    created_at: datetime
