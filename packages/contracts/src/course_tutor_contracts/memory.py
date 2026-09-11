"""Session-memory and learner-controlled long-term-memory API contracts."""

from __future__ import annotations

from datetime import datetime
from typing import Literal
from uuid import UUID

from pydantic import BaseModel, ConfigDict, Field, model_validator

from course_tutor_contracts.enums import MemoryFactStatus, MemoryFactType


class MemoryFactView(BaseModel):
    model_config = ConfigDict(extra="forbid", frozen=True, from_attributes=True)

    id: UUID
    course_id: UUID
    type: MemoryFactType
    normalized_key: str
    normalized_value: str
    confidence: float = Field(ge=0.0, le=1.0)
    importance: float = Field(ge=0.0, le=1.0)
    status: MemoryFactStatus
    pinned: bool
    evidence_turn_ids: tuple[UUID, ...]
    created_at: datetime
    updated_at: datetime
    expires_at: datetime | None = None
    reason: str


class MemoryUpdate(BaseModel):
    model_config = ConfigDict(extra="forbid")

    action: Literal["correct", "pin", "unpin", "delete"]
    normalized_value: str | None = Field(default=None, min_length=1, max_length=500)

    @model_validator(mode="after")
    def _correction_requires_value(self) -> MemoryUpdate:
        if self.action == "correct" and not self.normalized_value:
            raise ValueError("normalized_value is required for correction")
        if self.action != "correct" and self.normalized_value is not None:
            raise ValueError("normalized_value is only valid for correction")
        return self


class MemoryConsentUpdate(BaseModel):
    model_config = ConfigDict(extra="forbid")

    enabled: bool


class MemoryConsentView(BaseModel):
    model_config = ConfigDict(extra="forbid", frozen=True)

    course_id: UUID
    enabled: bool


class MemoryExport(BaseModel):
    model_config = ConfigDict(extra="forbid", frozen=True)

    exported_at: datetime
    course_id: UUID | None
    facts: tuple[MemoryFactView, ...]
