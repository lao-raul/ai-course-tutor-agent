"""A production release may not infer human approval from synthetic CI cases."""

from __future__ import annotations

from datetime import date

import pytest

from tests.evaluation.hiruzen.golden_gate import evaluate


def approved_report() -> dict:
    return {
        "book_family": "FLTRP Grade-3-start, Chen Lin, Grade 3 first term",
        "release_sha": "a" * 40,
        "content_version_id": "fixture-version",
        "model_version": "fixture-model",
        "prompt_version": "fixture-prompt",
        "ready_exercise_count": 20,
        "approval": {
            "reviewer": "test-reviewer",
            "decision": "approved",
            "reviewed_at": date.today().isoformat(),
        },
        "cases": [
            {
                "id": f"case-{index}",
                "schema_valid": True,
                "citation_valid": True,
                "evidence_covered": True,
                "answer_grounded": True,
                "ambiguous": False,
                "duplicate": False,
            }
            for index in range(20)
        ],
        "latency_ms": {
            "catalog_search": [100] * 20,
            "resume": [100] * 20,
            "generation_submit": [100] * 20,
        },
        "operational_evidence": {
            "availability_percent": 99.9,
            "availability": "monitoring/report-id",
            "worker_replay": "ci/replay-id",
            "log_redaction": "ci/redaction-id",
            "schema_isolation": "ci/schema-id",
            "correlation": "ci/trace-id",
            "ci_isolation": "ci/network-id",
            "security": "ci/security-id",
        },
    }


def test_approved_report_passes_thresholds() -> None:
    result = evaluate(approved_report(), release_sha="a" * 40)
    assert result["passed"] is True
    assert result["metrics"]["answer_key_groundedness"] == 1


def test_missing_human_approval_fails_closed() -> None:
    report = approved_report()
    del report["approval"]
    with pytest.raises(ValueError, match="human approval"):
        evaluate(report)


def test_wrong_release_fails_closed() -> None:
    with pytest.raises(ValueError, match="release SHA"):
        evaluate(approved_report(), release_sha="b" * 40)


def test_low_groundedness_and_duplicates_fail() -> None:
    report = approved_report()
    report["cases"][0]["answer_grounded"] = False
    report["cases"][1]["answer_grounded"] = False
    report["cases"][1]["duplicate"] = True
    result = evaluate(report)
    assert result["gates"]["HNFR-4"] is False
    assert result["passed"] is False


def test_missing_operational_evidence_fails() -> None:
    report = approved_report()
    del report["operational_evidence"]["security"]
    with pytest.raises(ValueError, match="security"):
        evaluate(report)
