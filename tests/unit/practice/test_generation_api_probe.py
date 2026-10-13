"""The deployed-API probe must catch the bad true/false stem seen in the pilot."""

from __future__ import annotations

import json
from argparse import Namespace
from pathlib import Path
from typing import Any

import pytest

from scripts import verify_practice_generation_api as probe


def _practice_set(prompt: str) -> dict[str, Any]:
    return {
        "id": "set-1",
        "exercises": [
            {
                "id": "exercise-1",
                "ordinal": 0,
                "prompt": prompt,
                "type": "true_false",
                "evidence_citation_ids": ["chunk-1"],
            }
        ],
        "evidence_sources": [{"chunk_id": "chunk-1"}],
    }


def test_api_audit_rejects_interrogative_true_false_and_unresolved_citation() -> None:
    practice_set = _practice_set("当有人问'Where's the pen?'时，正确的回答是什么？")  # noqa: RUF001
    practice_set["exercises"][0]["evidence_citation_ids"] = ["missing"]
    assert probe.audit_practice_set(practice_set, 1) == [
        "exercise 0: true_false prompt is not a complete claim",
        "exercise 0: unresolved citation missing",
    ]


def test_api_audit_catches_the_two_misclassified_pilot_exercises() -> None:
    practice_set = _practice_set("根据教材内容，当你向别人介绍父亲时，可能会说：")  # noqa: RUF001
    practice_set["exercises"].append(
        {
            "id": "exercise-2",
            "ordinal": 1,
            "prompt": "当有人递给你蛋糕时，对方可能会说什么?",  # noqa: RUF001
            "type": "fill_in_the_blank",
            "evidence_citation_ids": ["chunk-1"],
        }
    )
    assert probe.audit_practice_set(practice_set, 2) == [
        "exercise 0: true_false prompt is not a complete claim",
        "exercise 1: fill_in_the_blank prompt has no blank",
    ]


def test_api_audit_rejects_unverified_dialogue_pairing() -> None:
    practice_set = _practice_set("有人询问“这是什么?”时, 回答“你好, 猫”的英文表达是什么?")
    practice_set["exercises"][0]["type"] = "multiple_choice"
    assert probe.audit_practice_set(practice_set, 1) == ["exercise 0: unverified dialogue pairing"]


def test_api_probe_calls_endpoints_and_writes_learner_response(
    monkeypatch: pytest.MonkeyPatch, tmp_path: Path
) -> None:
    calls: list[tuple[str, dict[str, Any] | None]] = []
    responses = [
        {"id": "plan-1"},
        {"id": "job-1", "status": "ready", "practice_set_id": "set-1"},
        _practice_set("课文中的'What's this?'用于询问物品名称。"),
    ]

    def fake_request(
        base_url: str, path: str, token: str, body: dict[str, Any] | None = None
    ) -> dict[str, Any]:
        assert base_url == "http://127.0.0.1:28001"
        assert token == "redacted-test-token"
        calls.append((path, body))
        return responses.pop(0)

    monkeypatch.setenv("COURSE_TUTOR_AUTH_TOKEN", "redacted-test-token")
    monkeypatch.setattr(probe, "request_json", fake_request)
    output = tmp_path / "probe.json"
    args = Namespace(
        base_url="http://127.0.0.1:28001",
        book_id="book-1",
        module_id=None,
        count=1,
        difficulty="standard",
        language="zh",
        question_types=None,
        timeout=30,
        output=output,
    )
    assert probe.run(args) == 0
    assert [path for path, _ in calls] == [
        "/catalog/books/book-1/study-plan",
        "/catalog/books/book-1/generations",
        "/sets/set-1",
    ]
    assert calls[1][1] is not None and calls[1][1]["count"] == 1
    saved = json.loads(output.read_text(encoding="utf-8"))
    assert saved["audit_errors"] == []
    assert saved["practice_set"]["exercises"][0]["prompt"].startswith("课文中的")
    assert "redacted-test-token" not in output.read_text(encoding="utf-8")
    assert output.stat().st_mode & 0o777 == 0o600
