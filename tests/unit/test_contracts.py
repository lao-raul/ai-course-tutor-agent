"""Contract and ORM parity.

The DTOs in ``course_tutor_contracts`` and the tables in ``course_tutor_api.db`` describe
the same entities. These tests fail when one side gains a field or enum member the other
does not know about.
"""

from __future__ import annotations

import pytest
from pydantic import ValidationError
from sqlalchemy import Enum as SAEnum
from sqlalchemy import inspect

from course_tutor_api.db import Base
from course_tutor_api.db import models as orm
from course_tutor_contracts import MemoryFact, MemoryFactType, UserRole
from course_tutor_contracts import domain as dto

ENTITY_PAIRS = [
    (dto.Course, orm.Course),
    (dto.ContentVersion, orm.ContentVersion),
    (dto.SourceDocument, orm.SourceDocument),
    (dto.Chunk, orm.Chunk),
    (dto.ChatSession, orm.ChatSession),
    (dto.ChatTurn, orm.ChatTurn),
    (dto.MemoryFact, orm.MemoryFact),
]

# DTO field -> ORM column, where the names intentionally differ.
ALIASES = {
    "active_content_version": "active_content_version_id",
    "evidence_ids": "evidence_turn_ids",
    "content_version": "content_version_id",
}


@pytest.mark.parametrize(("dto_model", "orm_model"), ENTITY_PAIRS, ids=lambda m: m.__name__)
def test_every_dto_field_exists_on_the_table(dto_model, orm_model) -> None:  # type: ignore[no-untyped-def]
    columns = {c.key for c in inspect(orm_model).columns}
    missing = {
        field: ALIASES.get(field, field)
        for field in dto_model.model_fields
        if ALIASES.get(field, field) not in columns
    }
    assert not missing, (
        f"{dto_model.__name__} fields absent from {orm_model.__tablename__}: {missing}"
    )


@pytest.mark.parametrize(
    ("python_enum", "table", "column"),
    [
        (UserRole, orm.User, "role"),
        (MemoryFactType, orm.MemoryFact, "type"),
    ],
)
def test_enum_columns_store_every_member(python_enum, table, column) -> None:  # type: ignore[no-untyped-def]
    sa_type = inspect(table).columns[column].type
    assert isinstance(sa_type, SAEnum)
    assert set(sa_type.enums) == {member.value for member in python_enum}


def test_all_tables_are_registered() -> None:
    assert set(Base.metadata.tables) == {
        "audit_events",
        "chat_sessions",
        "chat_turns",
        "chunks",
        "content_version_sources",
        "content_versions",
        "courses",
        "course_runs",
        "memory_facts",
        "memory_settings",
        "outbox_events",
        "programmes",
        "retrieval_traces",
        "source_documents",
        "source_roots",
        "tenants",
        "users",
    }


def test_dtos_reject_unknown_fields() -> None:
    """Strict DTOs stop a renamed field from being silently dropped in transit."""
    with pytest.raises(ValidationError):
        MemoryFact.model_validate(
            {
                "id": "00000000-0000-0000-0000-000000000001",
                "user_id": "00000000-0000-0000-0000-000000000002",
                "type": "knowledge_level",
                "normalized_value": "understands Bayes rule",
                "confidence": 0.8,
                "importance": 0.5,
                "created_at": "2026-01-01T00:00:00Z",
                "unexpected_field": "boom",
            }
        )


@pytest.mark.parametrize("bad_confidence", [-0.1, 1.1])
def test_memory_fact_confidence_is_bounded(bad_confidence: float) -> None:
    with pytest.raises(ValidationError):
        MemoryFact(
            id="00000000-0000-0000-0000-000000000001",  # type: ignore[arg-type]
            user_id="00000000-0000-0000-0000-000000000002",  # type: ignore[arg-type]
            type=MemoryFactType.KNOWLEDGE_LEVEL,
            normalized_value="x",
            confidence=bad_confidence,
            importance=0.5,
            created_at="2026-01-01T00:00:00Z",  # type: ignore[arg-type]
        )


def test_memory_fact_type_is_closed() -> None:
    """Raw personal detail must not be promotable to a memory type."""
    assert "personal_detail" not in {member.value for member in MemoryFactType}
    with pytest.raises(ValidationError):
        MemoryFact(
            id="00000000-0000-0000-0000-000000000001",  # type: ignore[arg-type]
            user_id="00000000-0000-0000-0000-000000000002",  # type: ignore[arg-type]
            type="home_address",  # type: ignore[arg-type]
            normalized_value="x",
            confidence=0.5,
            importance=0.5,
            created_at="2026-01-01T00:00:00Z",  # type: ignore[arg-type]
        )
