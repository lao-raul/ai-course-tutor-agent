"""Stable v1 contracts for Hiruzen practice plans and generation jobs."""

from __future__ import annotations

from datetime import datetime
from enum import StrEnum
from typing import Annotated, Literal
from uuid import UUID

from pydantic import BaseModel, ConfigDict, Field


class PracticeModel(BaseModel):
    model_config = ConfigDict(extra="forbid", frozen=True)


class QuestionType(StrEnum):
    MULTIPLE_CHOICE = "multiple_choice"
    TRUE_FALSE = "true_false"
    FILL_IN_THE_BLANK = "fill_in_the_blank"
    SHORT_ANSWER = "short_answer"


class PracticeDifficulty(StrEnum):
    INTRODUCTORY = "introductory"
    STANDARD = "standard"
    CHALLENGE = "challenge"


class PracticeLanguage(StrEnum):
    ZH = "zh"
    EN = "en"
    BILINGUAL = "bilingual"


class GenerationStatus(StrEnum):
    QUEUED = "queued"
    RETRIEVING = "retrieving"
    GENERATING = "generating"
    VALIDATING = "validating"
    READY = "ready"
    FAILED = "failed"
    CANCELLED = "cancelled"


class PracticeCapabilities(PracticeModel):
    exercise_generation: Literal["asynchronous_jobs"] = "asynchronous_jobs"
    implemented_features: tuple[str, ...] = (
        "default_study_plan",
        "generation_jobs",
        "practice_sets",
    )


class GeneratePracticeRequest(BaseModel):
    count: int = Field(default=5, ge=1, le=20)
    course_id: UUID | None = None
    study_plan_id: UUID | None = None
    module_id: UUID | None = None
    # Retained for the deprecated v0.2 alias. Canonical clients use module_id.
    topic: str | None = Field(default=None, max_length=255)
    difficulty: PracticeDifficulty = PracticeDifficulty.STANDARD
    question_types: tuple[QuestionType, ...] = tuple(QuestionType)
    language: PracticeLanguage = PracticeLanguage.ZH

    model_config = ConfigDict(extra="forbid")


class StudyPlanModuleView(PracticeModel):
    id: UUID
    ordinal: int = Field(ge=0)
    title: str
    outline_node_id: str | None = None
    objectives: tuple[str, ...] = ()


class StudyPlanView(PracticeModel):
    id: UUID
    book_id: UUID
    course_id: UUID
    course_run_id: UUID
    content_version_id: UUID
    name: str
    revision: int = Field(ge=1)
    modules: tuple[StudyPlanModuleView, ...]


class PracticeGenerationView(PracticeModel):
    id: UUID
    study_plan_id: UUID
    book_id: UUID
    course_id: UUID
    content_version_id: UUID
    status: GenerationStatus
    requested_count: int = Field(ge=1, le=20)
    practice_set_id: UUID | None = None
    error_code: str | None = None
    retryable: bool | None = None
    created_at: datetime
    updated_at: datetime


class ChoiceOption(PracticeModel):
    id: str = Field(min_length=1, max_length=64)
    text: str = Field(min_length=1)


class ExerciseBase(PracticeModel):
    id: UUID
    ordinal: int = Field(ge=0)
    prompt: str = Field(min_length=1)
    difficulty: PracticeDifficulty
    language: PracticeLanguage
    evidence_citation_ids: tuple[str, ...]


class MultipleChoiceExerciseView(ExerciseBase):
    type: Literal[QuestionType.MULTIPLE_CHOICE] = QuestionType.MULTIPLE_CHOICE
    options: tuple[ChoiceOption, ...] = Field(min_length=2, max_length=6)


class TrueFalseExerciseView(ExerciseBase):
    type: Literal[QuestionType.TRUE_FALSE] = QuestionType.TRUE_FALSE


class FillInTheBlankExerciseView(ExerciseBase):
    type: Literal[QuestionType.FILL_IN_THE_BLANK] = QuestionType.FILL_IN_THE_BLANK


class RubricCriterion(PracticeModel):
    description: str = Field(min_length=1)
    weight: float = Field(gt=0, le=1)


class ShortAnswerExerciseView(ExerciseBase):
    type: Literal[QuestionType.SHORT_ANSWER] = QuestionType.SHORT_ANSWER
    rubric: tuple[RubricCriterion, ...] = Field(min_length=1, max_length=5)


ExerciseView = Annotated[
    MultipleChoiceExerciseView
    | TrueFalseExerciseView
    | FillInTheBlankExerciseView
    | ShortAnswerExerciseView,
    Field(discriminator="type"),
]


class ExerciseDraftBase(BaseModel):
    prompt: str = Field(min_length=1)
    difficulty: PracticeDifficulty
    language: PracticeLanguage
    evidence_citation_ids: tuple[str, ...] = Field(min_length=1)
    rationale: str = Field(min_length=1)

    model_config = ConfigDict(extra="forbid", frozen=True)


class MultipleChoiceExerciseDraft(ExerciseDraftBase):
    type: Literal[QuestionType.MULTIPLE_CHOICE] = QuestionType.MULTIPLE_CHOICE
    options: tuple[ChoiceOption, ...] = Field(min_length=2, max_length=6)
    correct_option_id: str


class TrueFalseExerciseDraft(ExerciseDraftBase):
    type: Literal[QuestionType.TRUE_FALSE] = QuestionType.TRUE_FALSE
    answer: bool


class FillInTheBlankExerciseDraft(ExerciseDraftBase):
    type: Literal[QuestionType.FILL_IN_THE_BLANK] = QuestionType.FILL_IN_THE_BLANK
    acceptable_answers: tuple[str, ...] = Field(min_length=1, max_length=10)


class ShortAnswerExerciseDraft(ExerciseDraftBase):
    type: Literal[QuestionType.SHORT_ANSWER] = QuestionType.SHORT_ANSWER
    rubric: tuple[RubricCriterion, ...] = Field(min_length=1, max_length=5)
    exemplar_answer: str = Field(min_length=1)
    pass_threshold: float = Field(default=0.7, gt=0, le=1)


ExerciseDraft = Annotated[
    MultipleChoiceExerciseDraft
    | TrueFalseExerciseDraft
    | FillInTheBlankExerciseDraft
    | ShortAnswerExerciseDraft,
    Field(discriminator="type"),
]


class PracticeSetView(PracticeModel):
    id: UUID
    generation_id: UUID
    study_plan_id: UUID
    book_id: UUID
    course_id: UUID
    content_version_id: UUID
    exercises: tuple[ExerciseView, ...]
    created_at: datetime


class PracticeError(PracticeModel):
    code: str
    message: str
    correlation_id: str


# Kept as an import alias for one contract version while clients migrate.
PracticeNotImplementedError = PracticeError
