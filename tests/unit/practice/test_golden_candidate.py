"""Fixed, non-cherry-picked selection for the real-textbook diagnostic sample."""

from __future__ import annotations

import json
from argparse import Namespace
from pathlib import Path

import pytest

from scripts import verify_practice_golden_candidate as candidate
from scripts.verify_practice_golden_candidate import select_units


def test_selects_named_units_and_excludes_review_nodes() -> None:
    plan = {
        "modules": [
            *(
                {"id": str(index), "title": f"Unit {index % 2 + 1} Topic {index}"}
                for index in range(20)
            ),
            {"id": "review", "title": "Unit 1"},
        ]
    }
    assert [unit["id"] for unit in select_units(plan)] == [str(i) for i in range(20)]


def test_refuses_incomplete_unit_selection() -> None:
    with pytest.raises(ValueError, match="expected 20 named Units"):
        select_units({"modules": [{"id": "1", "title": "Unit 1 Topic"}]})


def test_candidate_records_all_outcomes_and_three_latency_series(
    monkeypatch: pytest.MonkeyPatch, tmp_path: Path
) -> None:
    plan = {
        "content_version_id": "version-1",
        "modules": [
            {"id": str(index), "title": f"Unit {index % 2 + 1} Topic {index}"}
            for index in range(20)
        ],
    }
    created = 0

    def fake_request(_base_url: str, path: str, _token: str, body: object = None) -> dict:
        nonlocal created
        if path.endswith("/study-plan"):
            return plan
        if path.startswith("/catalog/books?") or path == "/resume":
            return {}
        if path.endswith("/generations") and body is not None:
            created += 1
            return {"id": f"job-{created}", "status": "ready", "practice_set_id": f"set-{created}"}
        if path.startswith("/sets/"):
            return {
                "exercises": [
                    {
                        "ordinal": 0,
                        "prompt": "Hello is a greeting.",
                        "type": "true_false",
                        "evidence_citation_ids": ["chunk-1"],
                    }
                ],
                "evidence_sources": [{"chunk_id": "chunk-1"}],
            }
        raise AssertionError(path)

    monkeypatch.setenv("COURSE_TUTOR_AUTH_TOKEN", "private-test-token")
    monkeypatch.setattr(candidate, "request_json", fake_request)
    output = tmp_path / "candidate.json"
    args = Namespace(base_url="http://127.0.0.1:28001", book_id="book-1", timeout=1, output=output)
    assert candidate.run(args) == 0
    report = json.loads(output.read_text(encoding="utf-8"))
    assert created == 20 and len(report["cases"]) == 20
    assert all(
        len(report["latency_ms"][key]) == 20
        for key in ("catalog_search", "resume", "generation_submit")
    )
    assert report["human_approved"] is False
    assert report["complete"] is True
    first_prefix = json.loads((tmp_path / "candidate-partial-01.json").read_text())
    assert first_prefix["complete"] is False and len(first_prefix["cases"]) == 1
    assert "private-test-token" not in output.read_text(encoding="utf-8")
