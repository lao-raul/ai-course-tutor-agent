"""Retrieval and chat API contracts."""

from __future__ import annotations

from uuid import UUID

from pydantic import BaseModel, Field

from course_tutor_contracts.enums import AccessLabel, AnchorType, ChunkClass


class RetrievalQuery(BaseModel):
    """Request to retrieve relevant chunks for a course question."""

    course_id: UUID
    query: str = Field(..., min_length=1, max_length=1000)
    access_label: AccessLabel = AccessLabel.ENROLLED
    limit: int = Field(default=10, ge=1, le=50)


class RetrievedChunk(BaseModel):
    """A chunk returned from retrieval, with its relevance score."""

    chunk_id: UUID
    source_id: UUID
    text: str
    relative_path: str
    mime_type: str
    anchor_type: AnchorType
    anchor_value: str
    chunk_class: ChunkClass
    score: float


class RetrievalResult(BaseModel):
    """Result of a retrieval search."""

    candidates: list[RetrievedChunk]
    total_indexed: int
    timings_ms: dict[str, float]


class ChatRequest(BaseModel):
    """Request to the chat endpoint."""

    # course_id is provided by the URL path, not the body.
    query: str = Field(..., min_length=1, max_length=2000)
    access_label: AccessLabel = AccessLabel.ENROLLED
    session_id: UUID | None = None

    model_config = {"extra": "forbid"}


class ChatCitation(BaseModel, frozen=True):
    """A citation rendered in the chat response."""

    chunk_id: UUID
    relative_path: str
    anchor_type: AnchorType
    anchor_value: str
    text_excerpt: str = Field(..., max_length=200)


class ChatResponse(BaseModel, frozen=True):
    """Non-streaming chat response (used for abstention)."""

    answer: str
    citations: list[ChatCitation] = Field(default_factory=list)
    trace_id: UUID | None = None
    abstained: bool = False
    abstention_reason: str | None = None
