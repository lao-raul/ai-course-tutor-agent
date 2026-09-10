"""Safe regressions replacing the former live-Leeds/live-database test."""

from __future__ import annotations

from pathlib import Path

import pytest
from course_tutor_ingestion.scanner import Scanner

from tests.support.postgres import assert_safe_test_database_dsn


def test_destructive_harness_rejects_normal_application_database() -> None:
    with pytest.raises(RuntimeError, match="refusing destructive test operation"):
        assert_safe_test_database_dsn(
            "postgresql+asyncpg://course_tutor:course_tutor@localhost:5432/course_tutor"
        )


def test_destructive_harness_accepts_explicit_test_database() -> None:
    assert (
        assert_safe_test_database_dsn(
            "postgresql+asyncpg://course_tutor:course_tutor@localhost:5432/course_tutor_test_local"
        )
        == "course_tutor_test_local"
    )


def test_repeated_generated_snapshot_is_stable(tmp_path: Path) -> None:
    (tmp_path / "lecture.md").write_text("# Search\nGenerated fixture", encoding="utf-8")
    (tmp_path / "exercise.txt").write_text("Question: explain BFS", encoding="utf-8")
    first = Scanner(tmp_path).scan()
    second = Scanner(tmp_path).scan()
    assert [(item.relative_path, item.checksum) for item in first] == [
        (item.relative_path, item.checksum) for item in second
    ]
    assert {item.relative_path for item in first} == {"exercise.txt", "lecture.md"}
