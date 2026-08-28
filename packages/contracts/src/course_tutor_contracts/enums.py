"""Closed enumerations.

Every vocabulary the system persists is closed. Free-form values are rejected at the
schema boundary — this is what makes memory validation deterministic (design-spec §5).
"""

from __future__ import annotations

from enum import StrEnum


class UserRole(StrEnum):
    STUDENT = "student"
    TEACHING_ASSISTANT = "teaching_assistant"
    INSTRUCTOR = "instructor"
    PLATFORM_ADMIN = "platform_admin"


class EducationLevel(StrEnum):
    PRIMARY = "primary"
    MIDDLE_SCHOOL = "middle_school"
    HIGH_SCHOOL = "high_school"
    UNDERGRADUATE = "undergraduate"
    POSTGRADUATE = "postgraduate"


class ContentVersionStatus(StrEnum):
    """A version is built in the background, then previewed, then published."""

    PENDING = "pending"
    BUILDING = "building"
    READY = "ready"
    PUBLISHED = "published"
    FAILED = "failed"
    ROLLED_BACK = "rolled_back"


class ExtractionStatus(StrEnum):
    PENDING = "pending"
    EXTRACTED = "extracted"
    OCR_EXTRACTED = "ocr_extracted"
    QUARANTINED = "quarantined"
    FAILED = "failed"


class AccessLabel(StrEnum):
    """Authorization scope carried on every source, chunk and vector payload."""

    PUBLIC = "public"
    ENROLLED = "enrolled"
    STAFF_ONLY = "staff_only"
    RESTRICTED = "restricted"


class AnchorType(StrEnum):
    """How a citation points back into the original document."""

    PAGE = "page"
    SLIDE = "slide"
    HEADING = "heading"
    TIMESTAMP = "timestamp"
    LINE_RANGE = "line_range"


class ChunkClass(StrEnum):
    """Exercise questions and their solutions are chunked separately so the hint-first
    policy can withhold solutions (function-spec FR-2.6)."""

    CONTENT = "content"
    EXERCISE_QUESTION = "exercise_question"
    EXERCISE_SOLUTION = "exercise_solution"
    ASSESSMENT = "assessment"


class MemoryFactType(StrEnum):
    """The only promotable fact types. Raw personal detail is never a member."""

    LEARNING_GOAL = "learning_goal"
    KNOWLEDGE_LEVEL = "knowledge_level"
    PREFERRED_LANGUAGE_STYLE = "preferred_language_style"
    STABLE_CONSTRAINT = "stable_constraint"
    MISCONCEPTION = "misconception"
    MASTERY_SIGNAL = "mastery_signal"
    ACTIVE_STUDY_PLAN = "active_study_plan"


class MemoryFactStatus(StrEnum):
    ACTIVE = "active"
    SUPERSEDED = "superseded"
    CONFLICTED = "conflicted"
    TOMBSTONED = "tombstoned"
