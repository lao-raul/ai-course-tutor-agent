"""Strict LLM output envelope and reproducibility metadata."""

from __future__ import annotations

from dataclasses import dataclass
from uuid import UUID

from pydantic import BaseModel, ConfigDict, Field

from course_tutor_contracts import ExerciseDraft, PracticeEvidenceResponse

PROMPT_VERSION = "hiruzen-grounded-v1"
VALIDATOR_VERSION = "hiruzen-validation-v1"


class GeneratedBatch(BaseModel):
    model_config = ConfigDict(extra="forbid", frozen=True)

    exercises: tuple[ExerciseDraft, ...] = Field(min_length=1, max_length=20)


@dataclass(frozen=True, slots=True)
class GenerationContext:
    evidence: PracticeEvidenceResponse


@dataclass(frozen=True, slots=True)
class GenerationOutcome:
    drafts: tuple[ExerciseDraft, ...]
    seed: int
    prompt_version: str
    model_version: str
    validator_version: str
    retrieval_trace_id: UUID
