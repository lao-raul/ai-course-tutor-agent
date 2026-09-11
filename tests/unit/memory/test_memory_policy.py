from __future__ import annotations

import json
import uuid
from datetime import UTC, datetime, timedelta

import pytest
from course_tutor_memory import (
    MAX_RECALLED_FACTS,
    MAX_RECALLED_TOKENS,
    MAX_SUMMARY_TOKENS,
    MemoryCandidate,
    RecallFact,
    Turn,
    bounded_recall,
    estimate_tokens,
    extract_memory_candidates,
    rolling_summary,
    validate_candidate,
)
from pydantic import ValidationError

from course_tutor_contracts.enums import MemoryFactStatus, MemoryFactType


def _candidate(**overrides: object) -> str:
    value = {
        "type": "preferred_language_style",
        "key": "response language",
        "value": "chinese",
        "confidence": 0.9,
        "importance": 0.7,
        "evidence_turn_id": str(uuid.uuid4()),
        "course_id": str(uuid.uuid4()),
    }
    value.update(overrides)
    return json.dumps(value)


def test_candidate_schema_is_strict_scoped_supported_and_non_sensitive() -> None:
    turn_id, course_id = uuid.uuid4(), uuid.uuid4()
    candidate = validate_candidate(
        _candidate(evidence_turn_id=str(turn_id), course_id=str(course_id)),
        evidence_text="请用中文回答。",
        expected_turn_id=turn_id,
        expected_course_id=course_id,
    )
    assert candidate.key == "response_language"

    with pytest.raises(ValidationError):
        MemoryCandidate.model_validate_json(_candidate(unexpected="raw transcript"))
    with pytest.raises(ValueError, match="scope"):
        validate_candidate(
            _candidate(evidence_turn_id=str(turn_id), course_id=str(uuid.uuid4())),
            evidence_text="请用中文回答。",
            expected_turn_id=turn_id,
            expected_course_id=course_id,
        )
    with pytest.raises(ValueError, match="sensitive"):
        validate_candidate(
            _candidate(evidence_turn_id=str(turn_id), course_id=str(course_id)),
            evidence_text="请用中文回答, 我的 password is dangerous.",
            expected_turn_id=turn_id,
            expected_course_id=course_id,
        )


def test_extraction_is_triggered_and_bilingual_allow_listed() -> None:
    turn_id, course_id = uuid.uuid4(), uuid.uuid4()
    facts = extract_memory_candidates(
        "我是初学者, 请用中文一步一步解释。",
        turn_id=turn_id,
        course_id=course_id,
        meaningful_turn_number=1,
    )
    assert {(fact.key, fact.value) for fact in facts} == {
        ("response_language", "chinese"),
        ("explanation_style", "step_by_step"),
        ("self_reported_level", "beginner"),
    }
    assert (
        extract_memory_candidates(
            "This is an ordinary course question.",
            turn_id=turn_id,
            course_id=course_id,
            meaningful_turn_number=1,
        )
        == []
    )


def test_summary_and_recall_enforce_hard_budgets_and_status() -> None:
    turns = [
        Turn(id=uuid.uuid4(), role="user", content=f"问题 {number} " + "x" * 500)
        for number in range(20)
    ]
    summary = rolling_summary(None, turns)
    assert estimate_tokens(summary) <= MAX_SUMMARY_TOKENS
    assert rolling_summary(summary, turns) == summary

    now = datetime.now(UTC)
    facts = [
        RecallFact(
            id=uuid.uuid4(),
            type=MemoryFactType.LEARNING_GOAL,
            value=f"learn Bayesian topic {number} " + "x" * 80,
            confidence=0.9,
            importance=0.8,
            updated_at=now,
        )
        for number in range(12)
    ]
    facts.extend(
        [
            RecallFact(
                id=uuid.uuid4(),
                type=MemoryFactType.KNOWLEDGE_LEVEL,
                value="expired",
                confidence=1,
                importance=1,
                updated_at=now,
                expires_at=now - timedelta(seconds=1),
            ),
            RecallFact(
                id=uuid.uuid4(),
                type=MemoryFactType.KNOWLEDGE_LEVEL,
                value="deleted",
                confidence=1,
                importance=1,
                updated_at=now,
                status=MemoryFactStatus.TOMBSTONED,
            ),
        ]
    )
    recalled = bounded_recall(facts, "Bayesian")
    assert len(recalled) <= MAX_RECALLED_FACTS
    assert sum(estimate_tokens(f"{fact.type.value}: {fact.value}") for fact in recalled) <= (
        MAX_RECALLED_TOKENS
    )
    assert {fact.value for fact in recalled}.isdisjoint({"expired", "deleted"})


def test_recall_confidence_decays_with_age() -> None:
    now = datetime.now(UTC)
    recent = RecallFact(
        id=uuid.uuid4(),
        type=MemoryFactType.LEARNING_GOAL,
        value="learn Bayesian inference",
        confidence=0.8,
        importance=0.5,
        updated_at=now,
    )
    stale = RecallFact(
        id=uuid.uuid4(),
        type=MemoryFactType.LEARNING_GOAL,
        value="learn Bayesian inference",
        confidence=0.8,
        importance=0.5,
        updated_at=now - timedelta(days=360),
    )
    assert bounded_recall([stale, recent], "Bayesian", now=now)[0].id == recent.id
