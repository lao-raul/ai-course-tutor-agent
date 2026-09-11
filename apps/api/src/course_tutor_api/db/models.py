"""ORM models (design-spec §3).

Tenancy is on every row that holds course or learner data, and the uniqueness
constraints encode the idempotency rules from function-spec FR-1: re-scanning an
unchanged file must not create a second source or duplicate chunks.
"""

from __future__ import annotations

import uuid
from datetime import datetime
from typing import Any

from sqlalchemy import (
    CheckConstraint,
    Enum,
    Float,
    ForeignKey,
    Index,
    Integer,
    String,
    Text,
    UniqueConstraint,
    text,
)
from sqlalchemy.dialects.postgresql import ARRAY, JSONB
from sqlalchemy.dialects.postgresql import UUID as PGUUID
from sqlalchemy.orm import Mapped, mapped_column

from course_tutor_api.db.base import Base, TimestampMixin, uuid_pk
from course_tutor_contracts.enums import (
    AccessLabel,
    AnchorType,
    ChunkClass,
    ContentVersionStatus,
    EducationLevel,
    ExtractionStatus,
    MemoryFactStatus,
    MemoryFactType,
    UserRole,
)


def _enum(python_enum: type, name: str) -> Enum:
    """Native PG enum storing the string *values*, not the member names."""
    return Enum(
        python_enum,
        name=name,
        values_callable=lambda enum_cls: [member.value for member in enum_cls],
    )


class Tenant(Base, TimestampMixin):
    __tablename__ = "tenants"

    id: Mapped[uuid.UUID] = uuid_pk()
    slug: Mapped[str] = mapped_column(String(64), unique=True)
    name: Mapped[str] = mapped_column(String(255))


class User(Base, TimestampMixin):
    __tablename__ = "users"
    __table_args__ = (UniqueConstraint("tenant_id", "external_subject"),)

    id: Mapped[uuid.UUID] = uuid_pk()
    tenant_id: Mapped[uuid.UUID] = mapped_column(ForeignKey("tenants.id", ondelete="CASCADE"))
    # OIDC subject; populated in Phase 4. Nullable so local development needs no IdP.
    external_subject: Mapped[str | None] = mapped_column(String(255))
    display_name: Mapped[str] = mapped_column(String(255))
    role: Mapped[UserRole] = mapped_column(_enum(UserRole, "user_role"))


class Programme(Base, TimestampMixin):
    __tablename__ = "programmes"
    __table_args__ = (UniqueConstraint("tenant_id", "code"),)

    id: Mapped[uuid.UUID] = uuid_pk()
    tenant_id: Mapped[uuid.UUID] = mapped_column(ForeignKey("tenants.id", ondelete="CASCADE"))
    code: Mapped[str] = mapped_column(String(64))
    name: Mapped[str] = mapped_column(String(255))


class SourceRoot(Base, TimestampMixin):
    """A mounted, read-only local directory holding course material."""

    __tablename__ = "source_roots"

    id: Mapped[uuid.UUID] = uuid_pk()
    tenant_id: Mapped[uuid.UUID] = mapped_column(ForeignKey("tenants.id", ondelete="CASCADE"))
    absolute_path: Mapped[str] = mapped_column(Text)
    last_scanned_at: Mapped[datetime | None] = mapped_column()
    last_snapshot_hash: Mapped[str | None] = mapped_column(String(64))
    scan_interval_seconds: Mapped[int] = mapped_column(Integer, default=900)


class Course(Base, TimestampMixin):
    __tablename__ = "courses"
    __table_args__ = (UniqueConstraint("tenant_id", "code"),)

    id: Mapped[uuid.UUID] = uuid_pk()
    tenant_id: Mapped[uuid.UUID] = mapped_column(ForeignKey("tenants.id", ondelete="CASCADE"))
    programme_id: Mapped[uuid.UUID] = mapped_column(
        ForeignKey("programmes.id", ondelete="RESTRICT")
    )
    code: Mapped[str] = mapped_column(String(64))
    name: Mapped[str] = mapped_column(String(255))
    level: Mapped[EducationLevel] = mapped_column(_enum(EducationLevel, "education_level"))
    # Publish/rollback is an alias swap, never a data rewrite (FR-1.3).
    active_content_version_id: Mapped[uuid.UUID | None] = mapped_column(
        PGUUID(as_uuid=True), ForeignKey("content_versions.id", use_alter=True)
    )
    source_root_id: Mapped[uuid.UUID | None] = mapped_column(ForeignKey("source_roots.id"))
    teaching_policy: Mapped[dict[str, Any]] = mapped_column(JSONB, default=dict)


class CourseRun(Base, TimestampMixin):
    __tablename__ = "course_runs"
    __table_args__ = (UniqueConstraint("course_id", "run_key"),)

    id: Mapped[uuid.UUID] = uuid_pk()
    course_id: Mapped[uuid.UUID] = mapped_column(ForeignKey("courses.id", ondelete="CASCADE"))
    run_key: Mapped[str] = mapped_column(String(128))
    source_root_id: Mapped[uuid.UUID] = mapped_column(ForeignKey("source_roots.id"))
    active_content_version_id: Mapped[uuid.UUID | None] = mapped_column(
        PGUUID(as_uuid=True), ForeignKey("content_versions.id", use_alter=True)
    )


class ContentVersion(Base, TimestampMixin):
    __tablename__ = "content_versions"
    __table_args__ = (UniqueConstraint("course_run_id", "pipeline_version", "sequence"),)

    id: Mapped[uuid.UUID] = uuid_pk()
    course_id: Mapped[uuid.UUID] = mapped_column(ForeignKey("courses.id", ondelete="CASCADE"))
    course_run_id: Mapped[uuid.UUID] = mapped_column(
        ForeignKey("course_runs.id", ondelete="CASCADE")
    )
    pipeline_version: Mapped[str] = mapped_column(String(64))
    sequence: Mapped[int] = mapped_column(Integer)
    status: Mapped[ContentVersionStatus] = mapped_column(
        _enum(ContentVersionStatus, "content_version_status")
    )
    embedding_model_version: Mapped[str] = mapped_column(String(128))
    embedding_dimension: Mapped[int] = mapped_column(Integer)
    source_snapshot_hash: Mapped[str | None] = mapped_column(String(64))
    published_at: Mapped[datetime | None] = mapped_column()


class SourceDocument(Base, TimestampMixin):
    __tablename__ = "source_documents"
    __table_args__ = (
        # Path is the immutable row identity inside a version. Checksums detect
        # changes, but duplicate files with identical bytes are valid inputs.
        UniqueConstraint("version_id", "relative_path", name="uq_source_documents_version_path"),
        Index("ix_source_documents_extraction_status", "extraction_status"),
        CheckConstraint(
            "extraction_confidence IS NULL "
            "OR (extraction_confidence >= 0 AND extraction_confidence <= 1)",
            name="extraction_confidence_range",
        ),
    )

    id: Mapped[uuid.UUID] = uuid_pk()
    version_id: Mapped[uuid.UUID] = mapped_column(
        ForeignKey("content_versions.id", ondelete="CASCADE")
    )
    relative_path: Mapped[str] = mapped_column(Text)
    checksum: Mapped[str] = mapped_column(String(64))
    mime_type: Mapped[str] = mapped_column(String(128))
    size_bytes: Mapped[int] = mapped_column(Integer)
    access_label: Mapped[AccessLabel] = mapped_column(_enum(AccessLabel, "access_label"))
    extraction_status: Mapped[ExtractionStatus] = mapped_column(
        _enum(ExtractionStatus, "extraction_status")
    )
    extraction_confidence: Mapped[float | None] = mapped_column(Float)
    failure_reason: Mapped[str | None] = mapped_column(Text)
    artifact_key: Mapped[str | None] = mapped_column(Text)
    # Week/topic and other instructor metadata preserved from the source tree.
    source_metadata: Mapped[dict[str, Any]] = mapped_column(JSONB, default=dict)


class Chunk(Base, TimestampMixin):
    __tablename__ = "chunks"
    __table_args__ = (
        UniqueConstraint("source_id", "ordinal"),
        Index("ix_chunks_source_class", "source_id", "chunk_class"),
    )

    id: Mapped[uuid.UUID] = uuid_pk()
    source_id: Mapped[uuid.UUID] = mapped_column(
        ForeignKey("source_documents.id", ondelete="CASCADE")
    )
    ordinal: Mapped[int] = mapped_column(Integer)
    text: Mapped[str] = mapped_column(Text)
    token_count: Mapped[int] = mapped_column(Integer)
    anchor_type: Mapped[AnchorType] = mapped_column(_enum(AnchorType, "anchor_type"))
    anchor_value: Mapped[str] = mapped_column(String(128))
    chunk_class: Mapped[ChunkClass] = mapped_column(
        _enum(ChunkClass, "chunk_class"), default=ChunkClass.CONTENT
    )
    embedding_model_version: Mapped[str] = mapped_column(String(128))


class ChatSession(Base, TimestampMixin):
    __tablename__ = "chat_sessions"
    __table_args__ = (Index("ix_chat_sessions_user_course", "user_id", "course_id"),)

    id: Mapped[uuid.UUID] = uuid_pk()
    user_id: Mapped[uuid.UUID] = mapped_column(ForeignKey("users.id", ondelete="CASCADE"))
    course_id: Mapped[uuid.UUID] = mapped_column(ForeignKey("courses.id", ondelete="CASCADE"))
    rolling_summary: Mapped[str | None] = mapped_column(Text)
    summary_token_count: Mapped[int] = mapped_column(Integer, default=0)
    expires_at: Mapped[datetime | None] = mapped_column()


class ChatTurn(Base, TimestampMixin):
    __tablename__ = "chat_turns"
    __table_args__ = (
        Index("ix_chat_turns_session_created", "session_id", "created_at"),
        CheckConstraint("role IN ('user', 'assistant')", name="role_known"),
        CheckConstraint("token_count >= 0", name="token_count_non_negative"),
    )

    id: Mapped[uuid.UUID] = uuid_pk()
    session_id: Mapped[uuid.UUID] = mapped_column(
        ForeignKey("chat_sessions.id", ondelete="CASCADE")
    )
    role: Mapped[str] = mapped_column(String(16))
    content: Mapped[str] = mapped_column(Text)
    token_count: Mapped[int] = mapped_column(Integer)


class MemorySetting(Base, TimestampMixin):
    __tablename__ = "memory_settings"
    __table_args__ = (UniqueConstraint("user_id", "course_id"),)

    id: Mapped[uuid.UUID] = uuid_pk()
    user_id: Mapped[uuid.UUID] = mapped_column(ForeignKey("users.id", ondelete="CASCADE"))
    course_id: Mapped[uuid.UUID] = mapped_column(ForeignKey("courses.id", ondelete="CASCADE"))
    enabled: Mapped[bool] = mapped_column(default=False)


class MemoryFact(Base, TimestampMixin):
    __tablename__ = "memory_facts"
    __table_args__ = (
        # First-pass dedup is deterministic on the normalized key (design-spec §5);
        # semantic similarity only runs on what survives this.
        Index(
            "uq_memory_facts_active_key",
            "user_id",
            "course_id",
            "type",
            "normalized_key",
            unique=True,
            postgresql_where=text("status = 'active'"),
        ),
        Index("ix_memory_facts_recall", "user_id", "course_id", "status"),
        CheckConstraint("confidence >= 0 AND confidence <= 1", name="confidence_range"),
        CheckConstraint("importance >= 0 AND importance <= 1", name="importance_range"),
    )

    id: Mapped[uuid.UUID] = uuid_pk()
    user_id: Mapped[uuid.UUID] = mapped_column(ForeignKey("users.id", ondelete="CASCADE"))
    # NULL means the fact is not course-scoped; cross-course recall needs consent.
    course_id: Mapped[uuid.UUID | None] = mapped_column(
        ForeignKey("courses.id", ondelete="CASCADE")
    )
    type: Mapped[MemoryFactType] = mapped_column(_enum(MemoryFactType, "memory_fact_type"))
    normalized_key: Mapped[str] = mapped_column(String(255))
    normalized_value: Mapped[str] = mapped_column(Text)
    confidence: Mapped[float] = mapped_column(Float)
    importance: Mapped[float] = mapped_column(Float)
    evidence_turn_ids: Mapped[list[uuid.UUID]] = mapped_column(
        ARRAY(PGUUID(as_uuid=True)), default=list
    )
    status: Mapped[MemoryFactStatus] = mapped_column(
        _enum(MemoryFactStatus, "memory_fact_status"), default=MemoryFactStatus.ACTIVE
    )
    pinned: Mapped[bool] = mapped_column(default=False)
    last_confirmed_at: Mapped[datetime | None] = mapped_column()
    expires_at: Mapped[datetime | None] = mapped_column()
    supersedes_id: Mapped[uuid.UUID | None] = mapped_column(
        ForeignKey("memory_facts.id", ondelete="SET NULL")
    )
    tombstoned_at: Mapped[datetime | None] = mapped_column()


class RetrievalTrace(Base, TimestampMixin):
    __tablename__ = "retrieval_traces"
    __table_args__ = (Index("ix_retrieval_traces_request", "request_id"),)

    id: Mapped[uuid.UUID] = uuid_pk()
    request_id: Mapped[str] = mapped_column(String(64))
    course_id: Mapped[uuid.UUID] = mapped_column(ForeignKey("courses.id", ondelete="CASCADE"))
    content_version_id: Mapped[uuid.UUID] = mapped_column(ForeignKey("content_versions.id"))
    query: Mapped[str] = mapped_column(Text)
    candidate_ids: Mapped[list[uuid.UUID]] = mapped_column(
        ARRAY(PGUUID(as_uuid=True)), default=list
    )
    reranked_ids: Mapped[list[uuid.UUID]] = mapped_column(ARRAY(PGUUID(as_uuid=True)), default=list)
    scores: Mapped[list[float]] = mapped_column(ARRAY(Float), default=list)
    timings_ms: Mapped[dict[str, Any]] = mapped_column(JSONB, default=dict)


class OutboxEvent(Base, TimestampMixin):
    """Transactional outbox. Consumers are idempotent on ``idempotency_key``, which is
    what makes a worker restart safe (acceptance criterion 5)."""

    __tablename__ = "outbox_events"
    __table_args__ = (
        UniqueConstraint("idempotency_key"),
        Index("ix_outbox_events_unprocessed", "processed_at"),
    )

    id: Mapped[uuid.UUID] = uuid_pk()
    topic: Mapped[str] = mapped_column(String(128))
    idempotency_key: Mapped[str] = mapped_column(String(255))
    payload: Mapped[dict[str, Any]] = mapped_column(JSONB)
    correlation_id: Mapped[str | None] = mapped_column(String(64))
    attempts: Mapped[int] = mapped_column(Integer, default=0)
    processed_at: Mapped[datetime | None] = mapped_column()
    dead_lettered_at: Mapped[datetime | None] = mapped_column()
    last_error: Mapped[str | None] = mapped_column(Text)


class AuditEvent(Base, TimestampMixin):
    """Append-only record of privileged and privacy-sensitive operations."""

    __tablename__ = "audit_events"
    __table_args__ = (
        Index("ix_audit_events_tenant_created", "tenant_id", "created_at"),
        Index("ix_audit_events_actor", "actor_user_id"),
    )

    id: Mapped[uuid.UUID] = uuid_pk()
    tenant_id: Mapped[uuid.UUID] = mapped_column(ForeignKey("tenants.id", ondelete="CASCADE"))
    actor_user_id: Mapped[uuid.UUID] = mapped_column(PGUUID(as_uuid=True))
    action: Mapped[str] = mapped_column(String(128))
    resource_type: Mapped[str] = mapped_column(String(64))
    resource_id: Mapped[str] = mapped_column(String(255))
    details: Mapped[dict[str, Any]] = mapped_column(JSONB, default=dict)
