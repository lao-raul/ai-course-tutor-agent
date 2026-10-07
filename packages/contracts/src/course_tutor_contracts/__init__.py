"""Versioned domain, API and event schemas.

This package is the single source of truth for cross-service shapes. It holds no
behaviour and no I/O, so services can depend on it without depending on each other.
"""

from course_tutor_contracts.domain import (
    Book,
    CatalogImportCandidate,
    Category,
    ChatSession,
    ChatTurn,
    Chunk,
    ContentVersion,
    Course,
    MemoryFact,
    Publisher,
    RetrievalTrace,
    SourceDocument,
)
from course_tutor_contracts.enums import (
    AccessLabel,
    AnchorType,
    BookLifecycleStatus,
    CatalogCandidateStatus,
    CatalogImportStatus,
    CategoryType,
    ChunkClass,
    ContentVersionStatus,
    EducationLevel,
    ExtractionStatus,
    MemoryFactStatus,
    MemoryFactType,
    UserRole,
)
from course_tutor_contracts.memory import (
    MemoryConsentUpdate,
    MemoryConsentView,
    MemoryExport,
    MemoryFactView,
    MemoryUpdate,
)
from course_tutor_contracts.practice import (
    GeneratePracticeRequest,
    PracticeCapabilities,
    PracticeNotImplementedError,
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
    "Book",
    "BookLifecycleStatus",
    "CatalogCandidateStatus",
    "CatalogImportCandidate",
    "CatalogImportStatus",
    "Category",
    "CategoryType",
    "ChatCitation",
    "ChatRequest",
    "ChatResponse",
    "ChatSession",
    "ChatTurn",
    "Chunk",
    "ChunkClass",
    "ContentVersion",
    "ContentVersionStatus",
    "Course",
    "EducationLevel",
    "ExtractionStatus",
    "GeneratePracticeRequest",
    "MemoryConsentUpdate",
    "MemoryConsentView",
    "MemoryExport",
    "MemoryFact",
    "MemoryFactStatus",
    "MemoryFactType",
    "MemoryFactView",
    "MemoryUpdate",
    "PracticeCapabilities",
    "PracticeNotImplementedError",
    "Publisher",
    "RetrievalQuery",
    "RetrievalResult",
    "RetrievalTrace",
    "RetrievedChunk",
    "SourceDocument",
    "UserRole",
]
