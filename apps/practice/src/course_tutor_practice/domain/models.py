"""Persistence-independent records used by the Hiruzen application layer."""

from __future__ import annotations

from dataclasses import dataclass, field
from datetime import datetime
from uuid import UUID

from course_tutor_contracts import ExerciseView, GenerationStatus


@dataclass(frozen=True, slots=True)
class ModuleRecord:
    id: UUID
    ordinal: int
    title: str
    outline_node_id: str | None = None
    objectives: tuple[str, ...] = ()


@dataclass(frozen=True, slots=True)
class StudyPlanRecord:
    id: UUID
    tenant_id: UUID
    book_id: UUID
    course_id: UUID
    course_run_id: UUID
    content_version_id: UUID
    name: str
    revision: int
    modules: tuple[ModuleRecord, ...]
    policy: dict[str, object] = field(default_factory=dict)


@dataclass(frozen=True, slots=True)
class GenerationRecord:
    id: UUID
    tenant_id: UUID
    user_id: UUID
    study_plan_id: UUID
    module_id: UUID | None
    book_id: UUID
    course_id: UUID
    course_run_id: UUID
    content_version_id: UUID
    idempotency_key: str
    request_payload: dict[str, object]
    requested_count: int
    status: GenerationStatus
    correlation_id: str
    deadline_at: datetime
    attempt_count: int
    created_at: datetime
    updated_at: datetime
    practice_set_id: UUID | None = None
    error_code: str | None = None
    retryable: bool | None = None


@dataclass(frozen=True, slots=True)
class PracticeSetRecord:
    id: UUID
    generation_id: UUID
    tenant_id: UUID
    user_id: UUID
    study_plan_id: UUID
    book_id: UUID
    course_id: UUID
    content_version_id: UUID
    exercises: tuple[ExerciseView, ...]
    created_at: datetime
