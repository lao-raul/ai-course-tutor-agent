"""Stable v1 contracts for the Practice API boundary."""

from __future__ import annotations

from typing import Literal

from pydantic import BaseModel, Field


class PracticeCapabilities(BaseModel, frozen=True):
    exercise_generation: Literal["not_implemented"] = "not_implemented"
    implemented_features: tuple[str, ...] = ()


class GeneratePracticeRequest(BaseModel):
    count: int = Field(default=5, ge=1, le=20)
    topic: str | None = Field(default=None, max_length=255)
    difficulty: str | None = Field(default=None, max_length=64)

    model_config = {"extra": "forbid"}


class PracticeNotImplementedError(BaseModel, frozen=True):
    code: Literal["practice_generation_not_implemented"] = "practice_generation_not_implemented"
    message: str
    correlation_id: str
