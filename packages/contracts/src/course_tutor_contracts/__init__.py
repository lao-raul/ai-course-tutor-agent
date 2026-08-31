"""Versioned domain, API and event schemas.

This package is the single source of truth for cross-service shapes. It holds no
behaviour and no I/O, so services can depend on it without depending on each other.
"""

from course_tutor_contracts.domain import (
    ChatSession,
    Chunk,
    ContentVersion,
    Course,
    MemoryFact,
    RetrievalTrace,
    SourceDocument,
)
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
from course_tutor_contracts.retrieval import (
    ChatCitation,
    ChatRequest,
    ChatResponse,
    RetrievalQuery,
    RetrievalResult,
    RetrievedChunk,
)

__all__ = [
    "AccessLabel",
    "AnchorType",
    "ChatCitation",
    "ChatRequest",
    "ChatResponse",
    "ChatSession",
    "Chunk",
    "ChunkClass",
    "ContentVersion",
    "ContentVersionStatus",
    "Course",
    "EducationLevel",
    "ExtractionStatus",
    "MemoryFact",
    "MemoryFactStatus",
    "MemoryFactType",
    "RetrievalQuery",
    "RetrievalResult",
    "RetrievalTrace",
    "RetrievedChunk",
    "SourceDocument",
    "UserRole",
]
