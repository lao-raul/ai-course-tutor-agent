"""Deterministic memory budgets, validation, recall and teaching policy.

This module deliberately performs no I/O. PostgreSQL remains the source of truth in
the Agent API, while these rules are independently testable and reusable by a future
memory worker.
"""

from __future__ import annotations

import json
import math
import re
from dataclasses import dataclass
from datetime import UTC, datetime
from difflib import SequenceMatcher
from typing import Literal
from uuid import UUID

from pydantic import BaseModel, ConfigDict, Field, field_validator

from course_tutor_contracts.enums import EducationLevel, MemoryFactStatus, MemoryFactType

MAX_SUMMARY_TOKENS = 500
MAX_RECENT_TURNS = 12
MAX_RECENT_TOKENS = 1_200
MAX_RECALLED_FACTS = 8
MAX_RECALLED_TOKENS = 350
MIN_MEMORY_CONFIDENCE = 0.65

_WHITESPACE = re.compile(r"\s+")
_KEY_CHARS = re.compile(r"[^a-z0-9]+")
_SENSITIVE = re.compile(
    r"(?:password|passcode|api[_ -]?key|secret|home address|postal address|"
    r"social security|national insurance|passport|medical diagnosis|银行卡|密码|"
    r"住址|身份证|护照|诊断|\b\+?\d[\d ()-]{8,}\d\b|"
    r"\b[A-Z0-9._%+-]+@[A-Z0-9.-]+\.[A-Z]{2,}\b)",
    re.IGNORECASE,
)
_EXPLICIT_MEMORY_SIGNAL = re.compile(
    r"(?:i prefer|please answer|my goal|i am (?:a )?(?:beginner|advanced)|"
    r"step[- ]by[- ]step|remember that|我希望|请用|我的目标|我是初学者|逐步|记住)",
    re.IGNORECASE,
)


def estimate_tokens(text: str) -> int:
    """Conservative tokenizer-independent estimate used for hard budgets."""
    return max(1, math.ceil(len(text) / 4)) if text else 0


def _bounded_text(text: str, max_tokens: int, *, keep_tail: bool = False) -> str:
    compact = _WHITESPACE.sub(" ", text).strip()
    max_chars = max_tokens * 4
    if len(compact) <= max_chars:
        return compact
    value = compact[-max_chars:] if keep_tail else compact[:max_chars]
    return value.strip()


def normalize_key(value: str) -> str:
    normalized = _KEY_CHARS.sub("_", value.casefold()).strip("_")
    if not normalized:
        raise ValueError("memory key must contain letters or numbers")
    return normalized[:255]


class Turn(BaseModel):
    model_config = ConfigDict(extra="forbid", frozen=True)

    id: UUID
    role: Literal["user", "assistant"]
    content: str = Field(min_length=1, max_length=20_000)


class MemoryCandidate(BaseModel):
    """Only this strict shape may cross the extraction/persistence boundary."""

    model_config = ConfigDict(extra="forbid", frozen=True)

    type: MemoryFactType
    key: str = Field(min_length=1, max_length=255)
    value: str = Field(min_length=1, max_length=500)
    confidence: float = Field(ge=MIN_MEMORY_CONFIDENCE, le=1.0)
    importance: float = Field(ge=0.0, le=1.0)
    evidence_turn_id: UUID
    course_id: UUID

    @field_validator("key")
    @classmethod
    def _normalize_key(cls, value: str) -> str:
        return normalize_key(value)

    @field_validator("value")
    @classmethod
    def _compact_value(cls, value: str) -> str:
        return _WHITESPACE.sub(" ", value).strip()


@dataclass(frozen=True, slots=True)
class RecallFact:
    id: UUID
    type: MemoryFactType
    value: str
    confidence: float
    importance: float
    updated_at: datetime
    status: MemoryFactStatus = MemoryFactStatus.ACTIVE
    pinned: bool = False
    expires_at: datetime | None = None


class TeachingPolicy(BaseModel):
    model_config = ConfigDict(extra="forbid", frozen=True)

    education_level: EducationLevel = EducationLevel.POSTGRADUATE
    explanation_style: Literal["concise", "balanced", "step_by_step", "detailed"] = "balanced"
    response_language: Literal["auto", "english", "chinese", "bilingual"] = "auto"
    solution_reveal_after_attempts: int = Field(default=4, ge=1, le=20)
    hint_stages: tuple[str, ...] = (
        "Ask a Socratic question that helps the learner identify the next concept.",
        "Give one conceptual hint without performing the solution step.",
        "Show one worked intermediate step, then ask the learner to continue.",
    )

    @field_validator("hint_stages")
    @classmethod
    def _require_hint_stages(cls, value: tuple[str, ...]) -> tuple[str, ...]:
        if not value or any(not item.strip() for item in value):
            raise ValueError("at least one non-empty hint stage is required")
        return value


def validate_candidate(
    raw_json: str,
    *,
    evidence_text: str,
    expected_turn_id: UUID,
    expected_course_id: UUID,
) -> MemoryCandidate:
    """Validate schema, scope, sensitivity and direct evidence before promotion."""
    candidate = MemoryCandidate.model_validate_json(raw_json)
    if candidate.evidence_turn_id != expected_turn_id or candidate.course_id != expected_course_id:
        raise ValueError("memory candidate scope does not match its evidence turn")
    if _SENSITIVE.search(candidate.value) or _SENSITIVE.search(evidence_text):
        raise ValueError("sensitive personal or secret data cannot become long-term memory")
    evidence_folded = _WHITESPACE.sub(" ", evidence_text).casefold()
    value_tokens = {
        item
        for item in re.findall(r"[\w\u3400-\u9fff]+", candidate.value.casefold())
        if len(item) > 1
    }
    supported = not value_tokens or any(token in evidence_folded for token in value_tokens)
    canonical_values = {
        "chinese",
        "english",
        "bilingual",
        "concise",
        "step_by_step",
        "detailed",
        "beginner",
        "advanced",
    }
    if not supported and candidate.value not in canonical_values:
        raise ValueError("memory candidate value is unsupported by the evidence turn")
    return candidate


def _candidate_json(
    fact_type: MemoryFactType,
    key: str,
    value: str,
    turn_id: UUID,
    course_id: UUID,
    *,
    confidence: float = 0.9,
    importance: float = 0.7,
) -> str:
    return json.dumps(
        {
            "type": fact_type.value,
            "key": key,
            "value": value,
            "confidence": confidence,
            "importance": importance,
            "evidence_turn_id": str(turn_id),
            "course_id": str(course_id),
        }
    )


def extract_memory_candidates(
    text: str,
    *,
    turn_id: UUID,
    course_id: UUID,
    meaningful_turn_number: int,
    trigger_interval: int = 2,
) -> list[MemoryCandidate]:
    """Extract a small allow-listed set only on meaningful turns.

    Extraction is intentionally conservative. It emits strict JSON and immediately
    validates that JSON through :class:`MemoryCandidate`; arbitrary transcript text is
    never copied wholesale into long-term memory.
    """
    compact = _WHITESPACE.sub(" ", text).strip()
    has_explicit_signal = _EXPLICIT_MEMORY_SIGNAL.search(compact) is not None
    if _SENSITIVE.search(compact) or (len(compact) < 8 and not has_explicit_signal):
        return []
    if meaningful_turn_number % max(1, trigger_interval) and not has_explicit_signal:
        return []

    lowered = compact.casefold()
    raw: list[str] = []
    if re.search(r"(?:请用|用中文|in chinese|chinese response)", lowered):
        raw.append(
            _candidate_json(
                MemoryFactType.PREFERRED_LANGUAGE_STYLE,
                "response_language",
                "chinese",
                turn_id,
                course_id,
            )
        )
    elif re.search(r"(?:用英文|in english|english response)", lowered):
        raw.append(
            _candidate_json(
                MemoryFactType.PREFERRED_LANGUAGE_STYLE,
                "response_language",
                "english",
                turn_id,
                course_id,
            )
        )
    elif re.search(r"(?:中英|bilingual)", lowered):
        raw.append(
            _candidate_json(
                MemoryFactType.PREFERRED_LANGUAGE_STYLE,
                "response_language",
                "bilingual",
                turn_id,
                course_id,
            )
        )

    if re.search(r"(?:逐步|一步一步|step[- ]by[- ]step)", lowered):
        raw.append(
            _candidate_json(
                MemoryFactType.PREFERRED_LANGUAGE_STYLE,
                "explanation_style",
                "step_by_step",
                turn_id,
                course_id,
            )
        )
    elif re.search(r"(?:简洁|concise|brief answers?)", lowered):
        raw.append(
            _candidate_json(
                MemoryFactType.PREFERRED_LANGUAGE_STYLE,
                "explanation_style",
                "concise",
                turn_id,
                course_id,
            )
        )

    if re.search(r"(?:我是初学者|i am (?:a )?beginner|i'm (?:a )?beginner)", lowered):
        raw.append(
            _candidate_json(
                MemoryFactType.KNOWLEDGE_LEVEL,
                "self_reported_level",
                "beginner",
                turn_id,
                course_id,
            )
        )

    goal_match = re.search(
        r"(?:my goal is|我的目标是)\s*[:\uFF1A]?\s*(?P<goal>[^。.!?]{3,160})",
        compact,
        re.IGNORECASE,
    )
    if goal_match:
        raw.append(
            _candidate_json(
                MemoryFactType.LEARNING_GOAL,
                "primary_learning_goal",
                goal_match.group("goal").strip(),
                turn_id,
                course_id,
                importance=0.85,
            )
        )

    validated: list[MemoryCandidate] = []
    for value in raw:
        try:
            validated.append(
                validate_candidate(
                    value,
                    evidence_text=compact,
                    expected_turn_id=turn_id,
                    expected_course_id=course_id,
                )
            )
        except ValueError:
            continue
    return validated


def semantic_similarity(left: str, right: str) -> float:
    """Deterministic semantic-ish duplicate guard after normalized-key matching."""
    left_value = _WHITESPACE.sub(" ", left).casefold().strip()
    right_value = _WHITESPACE.sub(" ", right).casefold().strip()
    if left_value == right_value:
        return 1.0
    left_tokens = set(re.findall(r"[\w\u3400-\u9fff]+", left_value))
    right_tokens = set(re.findall(r"[\w\u3400-\u9fff]+", right_value))
    union = left_tokens | right_tokens
    jaccard = len(left_tokens & right_tokens) / len(union) if union else 0.0
    return max(jaccard, SequenceMatcher(a=left_value, b=right_value).ratio())


def rolling_summary(previous: str | None, turns: list[Turn]) -> str:
    lines = [line for line in (previous or "").splitlines() if line]
    seen = set(lines)
    for turn in turns:
        line = f"{'Learner' if turn.role == 'user' else 'Tutor'}: {_bounded_text(turn.content, 80)}"
        if line not in seen:
            lines.append(line)
            seen.add(line)
    return _bounded_text("\n".join(lines), MAX_SUMMARY_TOKENS, keep_tail=True)


def recent_turn_window(turns: list[Turn]) -> tuple[Turn, ...]:
    selected: list[Turn] = []
    remaining = MAX_RECENT_TOKENS
    for turn in reversed(turns):
        tokens = estimate_tokens(turn.content)
        if len(selected) >= MAX_RECENT_TURNS or tokens > remaining:
            break
        selected.append(turn)
        remaining -= tokens
    return tuple(reversed(selected))


def _recall_score(fact: RecallFact, query: str, now: datetime) -> float:
    relevance = semantic_similarity(fact.value, query)
    age_days = max(0.0, (now - fact.updated_at.replace(tzinfo=UTC)).total_seconds() / 86_400)
    freshness = math.exp(-age_days / 90)
    effective_confidence = fact.confidence * math.exp(-age_days / 180)
    return (
        (1.0 if fact.pinned else 0.0)
        + 0.35 * relevance
        + 0.3 * fact.importance
        + 0.2 * effective_confidence
        + 0.15 * freshness
    )


def bounded_recall(
    facts: list[RecallFact], query: str, *, now: datetime | None = None
) -> tuple[RecallFact, ...]:
    current = now or datetime.now(UTC)
    eligible = [
        fact
        for fact in facts
        if fact.status is MemoryFactStatus.ACTIVE
        and (fact.expires_at is None or fact.expires_at.replace(tzinfo=UTC) > current)
    ]
    eligible.sort(key=lambda fact: _recall_score(fact, query, current), reverse=True)
    selected: list[RecallFact] = []
    remaining = MAX_RECALLED_TOKENS
    for fact in eligible:
        tokens = estimate_tokens(f"{fact.type.value}: {fact.value}")
        if len(selected) >= MAX_RECALLED_FACTS:
            break
        if tokens > remaining:
            continue
        selected.append(fact)
        remaining -= tokens
    return tuple(selected)


def solution_content_allowed(policy: TeachingPolicy, attempt_number: int) -> bool:
    return attempt_number >= policy.solution_reveal_after_attempts


def build_teaching_directive(
    policy: TeachingPolicy, *, assessment_mode: bool, attempt_number: int
) -> str:
    language = {
        "auto": "Use the learner's language.",
        "english": "Answer in English.",
        "chinese": "Use clear Simplified Chinese.",
        "bilingual": "Explain in Chinese first, then give concise English terminology.",
    }[policy.response_language]
    directive = (
        f"Teaching level: {policy.education_level.value}. "
        f"Explanation style: {policy.explanation_style}. {language} "
        "Label generated guidance as AI tutoring, not official instructor guidance."
    )
    if not assessment_mode:
        return directive
    if solution_content_allowed(policy, attempt_number):
        return (
            f"{directive} The configured attempt threshold is met; a worked solution may be shown."
        )
    stage = policy.hint_stages[min(max(attempt_number, 1) - 1, len(policy.hint_stages) - 1)]
    return (
        f"{directive} This is assessed work at attempt {attempt_number}. {stage} "
        "Do not quote, reveal, or reconstruct stored solution or assessment-answer chunks."
    )
