"""Versioned Agent-to-Hiruzen textbook evidence contract."""

from __future__ import annotations

from uuid import UUID

from pydantic import BaseModel, ConfigDict, Field

from course_tutor_contracts.enums import AnchorType, ChunkClass


class EvidenceModel(BaseModel):
    model_config = ConfigDict(extra="forbid", frozen=True)


class PracticeEvidenceRequest(EvidenceModel):
    generation_id: UUID
    book_id: UUID
    course_id: UUID
    content_version_id: UUID
    query: str = Field(min_length=1, max_length=1000)
    limit: int = Field(default=5, ge=1, le=20)


class PracticeEvidenceChunk(EvidenceModel):
    chunk_id: UUID
    source_id: UUID
    text: str = Field(min_length=1)
    relative_path: str
    anchor_type: AnchorType
    anchor_value: str
    chunk_class: ChunkClass
    score: float = Field(ge=0)


class PracticeEvidenceResponse(EvidenceModel):
    generation_id: UUID
    book_id: UUID
    course_id: UUID
    content_version_id: UUID
    retrieval_trace_id: UUID
    retrieval_policy_version: str
    allowed_content_classes: tuple[ChunkClass, ...]
    solution_release_after_incorrect_attempts: int = Field(ge=1)
    chunks: tuple[PracticeEvidenceChunk, ...]
