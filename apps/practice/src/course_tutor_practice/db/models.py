"""Hiruzen ORM models with no foreign keys into Agent-owned schemas."""

from __future__ import annotations

import uuid
from datetime import datetime
from typing import Any

from sqlalchemy import (
    Boolean,
    CheckConstraint,
    DateTime,
    Float,
    ForeignKey,
    Index,
    Integer,
    String,
    Text,
    UniqueConstraint,
    func,
)
from sqlalchemy.dialects.postgresql import JSONB
from sqlalchemy.dialects.postgresql import UUID as PGUUID
from sqlalchemy.orm import Mapped, mapped_column

from course_tutor_practice.db.base import Base, TimestampMixin, uuid_pk


class StudyPlan(Base, TimestampMixin):
    __tablename__ = "study_plans"
    __table_args__ = (
        UniqueConstraint(
            "tenant_id",
            "agent_book_id",
            "agent_content_version_id",
            name="uq_study_plan_book_content_version",
        ),
        Index("ix_study_plans_tenant_book", "tenant_id", "agent_book_id"),
    )

    id: Mapped[uuid.UUID] = uuid_pk()
    tenant_id: Mapped[uuid.UUID] = mapped_column(PGUUID(as_uuid=True))
    agent_book_id: Mapped[uuid.UUID] = mapped_column(PGUUID(as_uuid=True))
    agent_course_id: Mapped[uuid.UUID] = mapped_column(PGUUID(as_uuid=True))
    agent_course_run_id: Mapped[uuid.UUID] = mapped_column(PGUUID(as_uuid=True))
    agent_content_version_id: Mapped[uuid.UUID] = mapped_column(PGUUID(as_uuid=True))
    name: Mapped[str] = mapped_column(String(500))
    revision: Mapped[int] = mapped_column(Integer, default=1)
    policy: Mapped[dict[str, Any]] = mapped_column(JSONB, default=dict)


class StudyPlanModule(Base, TimestampMixin):
    __tablename__ = "study_plan_modules"
    __table_args__ = (
        UniqueConstraint("study_plan_id", "ordinal", name="uq_study_plan_module_ordinal"),
    )

    id: Mapped[uuid.UUID] = uuid_pk()
    study_plan_id: Mapped[uuid.UUID] = mapped_column(
        ForeignKey("practice.study_plans.id", ondelete="CASCADE")
    )
    ordinal: Mapped[int] = mapped_column(Integer)
    title: Mapped[str] = mapped_column(String(500))
    outline_node_id: Mapped[str | None] = mapped_column(String(96))
    objectives: Mapped[list[str]] = mapped_column(JSONB, default=list)


class GenerationJob(Base, TimestampMixin):
    __tablename__ = "generation_jobs"
    __table_args__ = (
        UniqueConstraint(
            "tenant_id", "user_id", "idempotency_key", name="uq_generation_idempotency"
        ),
        CheckConstraint(
            "status IN ('queued','retrieving','generating','validating',"
            "'ready','failed','cancelled')",
            name="generation_status_known",
        ),
        CheckConstraint("requested_count BETWEEN 1 AND 20", name="generation_count_range"),
        Index("ix_generation_jobs_owner", "tenant_id", "user_id", "created_at"),
        Index("ix_generation_jobs_status_deadline", "status", "deadline_at"),
    )

    id: Mapped[uuid.UUID] = uuid_pk()
    tenant_id: Mapped[uuid.UUID] = mapped_column(PGUUID(as_uuid=True))
    user_id: Mapped[uuid.UUID] = mapped_column(PGUUID(as_uuid=True))
    study_plan_id: Mapped[uuid.UUID] = mapped_column(
        ForeignKey("practice.study_plans.id", ondelete="RESTRICT")
    )
    module_id: Mapped[uuid.UUID | None] = mapped_column(
        ForeignKey("practice.study_plan_modules.id", ondelete="RESTRICT")
    )
    agent_book_id: Mapped[uuid.UUID] = mapped_column(PGUUID(as_uuid=True))
    agent_course_id: Mapped[uuid.UUID] = mapped_column(PGUUID(as_uuid=True))
    agent_course_run_id: Mapped[uuid.UUID] = mapped_column(PGUUID(as_uuid=True))
    agent_content_version_id: Mapped[uuid.UUID] = mapped_column(PGUUID(as_uuid=True))
    idempotency_key: Mapped[str] = mapped_column(String(255))
    request_payload: Mapped[dict[str, Any]] = mapped_column(JSONB)
    requested_count: Mapped[int] = mapped_column(Integer)
    status: Mapped[str] = mapped_column(String(16), default="queued")
    correlation_id: Mapped[str] = mapped_column(String(64))
    deadline_at: Mapped[datetime] = mapped_column(DateTime(timezone=True))
    attempt_count: Mapped[int] = mapped_column(Integer, default=0)
    lease_owner: Mapped[str | None] = mapped_column(String(128))
    lease_expires_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True))
    error_code: Mapped[str | None] = mapped_column(String(64))
    error_detail: Mapped[str | None] = mapped_column(Text)
    retryable: Mapped[bool | None]


class PracticeSet(Base, TimestampMixin):
    __tablename__ = "practice_sets"
    __table_args__ = (UniqueConstraint("generation_job_id"),)

    id: Mapped[uuid.UUID] = uuid_pk()
    generation_job_id: Mapped[uuid.UUID] = mapped_column(
        ForeignKey("practice.generation_jobs.id", ondelete="RESTRICT")
    )
    tenant_id: Mapped[uuid.UUID] = mapped_column(PGUUID(as_uuid=True))
    user_id: Mapped[uuid.UUID] = mapped_column(PGUUID(as_uuid=True))
    study_plan_id: Mapped[uuid.UUID] = mapped_column(
        ForeignKey("practice.study_plans.id", ondelete="RESTRICT")
    )
    agent_book_id: Mapped[uuid.UUID] = mapped_column(PGUUID(as_uuid=True))
    agent_course_id: Mapped[uuid.UUID] = mapped_column(PGUUID(as_uuid=True))
    agent_content_version_id: Mapped[uuid.UUID] = mapped_column(PGUUID(as_uuid=True))
    seed: Mapped[int] = mapped_column(Integer)
    prompt_version: Mapped[str] = mapped_column(String(64))
    model_version: Mapped[str] = mapped_column(String(255))
    validator_version: Mapped[str] = mapped_column(String(64))
    evidence_chunk_ids: Mapped[list[str]] = mapped_column(JSONB, default=list)
    correlation_id: Mapped[str] = mapped_column(String(64))
    retrieval_trace_id: Mapped[uuid.UUID | None] = mapped_column(PGUUID(as_uuid=True))


class Exercise(Base, TimestampMixin):
    __tablename__ = "exercises"
    __table_args__ = (
        UniqueConstraint("practice_set_id", "ordinal"),
        CheckConstraint(
            "question_type IN ('multiple_choice','true_false','fill_in_the_blank','short_answer')",
            name="exercise_type_known",
        ),
    )

    id: Mapped[uuid.UUID] = uuid_pk()
    practice_set_id: Mapped[uuid.UUID] = mapped_column(
        ForeignKey("practice.practice_sets.id", ondelete="CASCADE")
    )
    ordinal: Mapped[int] = mapped_column(Integer)
    question_type: Mapped[str] = mapped_column(String(32))
    presentation: Mapped[dict[str, Any]] = mapped_column(JSONB)
    protected_answer: Mapped[dict[str, Any]] = mapped_column(JSONB)
    rationale: Mapped[str] = mapped_column(Text)
    evidence_citation_ids: Mapped[list[str]] = mapped_column(JSONB, default=list)
    fingerprint: Mapped[str] = mapped_column(String(64), index=True)


class PracticeOutboxEvent(Base, TimestampMixin):
    __tablename__ = "outbox_events"
    __table_args__ = (
        UniqueConstraint("idempotency_key"),
        Index("ix_practice_outbox_claim", "processed_at", "lease_expires_at"),
    )

    id: Mapped[uuid.UUID] = uuid_pk()
    generation_job_id: Mapped[uuid.UUID] = mapped_column(
        ForeignKey("practice.generation_jobs.id", ondelete="CASCADE")
    )
    topic: Mapped[str] = mapped_column(String(128))
    idempotency_key: Mapped[str] = mapped_column(String(255))
    payload: Mapped[dict[str, Any]] = mapped_column(JSONB)
    correlation_id: Mapped[str] = mapped_column(String(64))
    attempts: Mapped[int] = mapped_column(Integer, default=0)
    lease_owner: Mapped[str | None] = mapped_column(String(128))
    lease_expires_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True))
    processed_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True))
    dead_lettered_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True))
    last_error: Mapped[str | None] = mapped_column(Text)


class Attempt(Base):
    __tablename__ = "attempts"
    __table_args__ = (
        UniqueConstraint(
            "tenant_id",
            "user_id",
            "exercise_id",
            "idempotency_key",
            name="uq_attempt_idempotency",
        ),
        UniqueConstraint(
            "tenant_id",
            "user_id",
            "exercise_id",
            "attempt_number",
            name="uq_attempt_ordinal",
        ),
        CheckConstraint("attempt_number BETWEEN 1 AND 4", name="attempt_number_range"),
        CheckConstraint("action IN ('submit','give_up')", name="attempt_action_known"),
        Index("ix_attempts_owner_set", "tenant_id", "user_id", "practice_set_id"),
    )

    id: Mapped[uuid.UUID] = uuid_pk()
    tenant_id: Mapped[uuid.UUID] = mapped_column(PGUUID(as_uuid=True))
    user_id: Mapped[uuid.UUID] = mapped_column(PGUUID(as_uuid=True))
    practice_set_id: Mapped[uuid.UUID] = mapped_column(ForeignKey("practice.practice_sets.id"))
    exercise_id: Mapped[uuid.UUID] = mapped_column(ForeignKey("practice.exercises.id"))
    attempt_number: Mapped[int] = mapped_column(Integer)
    action: Mapped[str] = mapped_column(String(16))
    idempotency_key: Mapped[str] = mapped_column(String(255))
    request_digest: Mapped[str] = mapped_column(String(64))
    submitted_value: Mapped[Any | None] = mapped_column(JSONB)
    correct: Mapped[bool | None] = mapped_column(Boolean)
    score: Mapped[float | None] = mapped_column(Float)
    provisional: Mapped[bool] = mapped_column(Boolean)
    evaluator: Mapped[str] = mapped_column(String(64))
    evaluator_version: Mapped[str] = mapped_column(String(255))
    created_at: Mapped[datetime] = mapped_column(server_default=func.now())


class StudyActivity(Base):
    __tablename__ = "study_activity"
    __table_args__ = (
        UniqueConstraint("tenant_id", "user_id", "source_key"),
        Index("ix_study_activity_owner_set", "tenant_id", "user_id", "practice_set_id"),
    )

    id: Mapped[uuid.UUID] = uuid_pk()
    tenant_id: Mapped[uuid.UUID] = mapped_column(PGUUID(as_uuid=True))
    user_id: Mapped[uuid.UUID] = mapped_column(PGUUID(as_uuid=True))
    practice_set_id: Mapped[uuid.UUID | None] = mapped_column(
        ForeignKey("practice.practice_sets.id")
    )
    exercise_id: Mapped[uuid.UUID | None] = mapped_column(ForeignKey("practice.exercises.id"))
    event_type: Mapped[str] = mapped_column(String(32))
    source_key: Mapped[str] = mapped_column(String(255))
    created_at: Mapped[datetime] = mapped_column(server_default=func.now())


class StudyProgress(Base, TimestampMixin):
    __tablename__ = "study_progress"
    __table_args__ = (UniqueConstraint("tenant_id", "user_id", "practice_set_id"),)

    id: Mapped[uuid.UUID] = uuid_pk()
    tenant_id: Mapped[uuid.UUID] = mapped_column(PGUUID(as_uuid=True))
    user_id: Mapped[uuid.UUID] = mapped_column(PGUUID(as_uuid=True))
    practice_set_id: Mapped[uuid.UUID] = mapped_column(ForeignKey("practice.practice_sets.id"))
    status: Mapped[str] = mapped_column(String(16))
    total_questions: Mapped[int] = mapped_column(Integer)
    attempted_questions: Mapped[int] = mapped_column(Integer)
    completed_questions: Mapped[int] = mapped_column(Integer)
    correct_questions: Mapped[int] = mapped_column(Integer)
    next_exercise_id: Mapped[uuid.UUID | None] = mapped_column(PGUUID(as_uuid=True))
    latest_activity_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True))
    topic_mastery: Mapped[dict[str, float]] = mapped_column(JSONB, default=dict)


class ResumeCursor(Base, TimestampMixin):
    __tablename__ = "resume_cursors"
    __table_args__ = (UniqueConstraint("tenant_id", "user_id"),)

    id: Mapped[uuid.UUID] = uuid_pk()
    tenant_id: Mapped[uuid.UUID] = mapped_column(PGUUID(as_uuid=True))
    user_id: Mapped[uuid.UUID] = mapped_column(PGUUID(as_uuid=True))
    practice_set_id: Mapped[uuid.UUID | None] = mapped_column(
        ForeignKey("practice.practice_sets.id")
    )
    exercise_id: Mapped[uuid.UUID | None] = mapped_column(PGUUID(as_uuid=True))
    cleared: Mapped[bool] = mapped_column(Boolean, default=False)


class ExerciseReport(Base):
    __tablename__ = "exercise_reports"
    __table_args__ = (UniqueConstraint("tenant_id", "user_id", "exercise_id", "idempotency_key"),)

    id: Mapped[uuid.UUID] = uuid_pk()
    tenant_id: Mapped[uuid.UUID] = mapped_column(PGUUID(as_uuid=True))
    user_id: Mapped[uuid.UUID] = mapped_column(PGUUID(as_uuid=True))
    exercise_id: Mapped[uuid.UUID] = mapped_column(ForeignKey("practice.exercises.id"))
    idempotency_key: Mapped[str] = mapped_column(String(255))
    reason: Mapped[str] = mapped_column(String(32))
    detail: Mapped[str] = mapped_column(Text)
    status: Mapped[str] = mapped_column(String(16), default="open")
    created_at: Mapped[datetime] = mapped_column(server_default=func.now())


class StudyMemoryConsent(Base, TimestampMixin):
    __tablename__ = "study_memory_consent"
    __table_args__ = (UniqueConstraint("tenant_id", "user_id"),)

    id: Mapped[uuid.UUID] = uuid_pk()
    tenant_id: Mapped[uuid.UUID] = mapped_column(PGUUID(as_uuid=True))
    user_id: Mapped[uuid.UUID] = mapped_column(PGUUID(as_uuid=True))
    enabled: Mapped[bool] = mapped_column(Boolean, default=False)
