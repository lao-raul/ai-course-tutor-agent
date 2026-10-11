"""Fail-closed release gate for a human-reviewed, redacted FLTRP pilot report."""

from __future__ import annotations

import argparse
import json
import math
from datetime import date
from pathlib import Path

MANIFEST = Path(__file__).with_name("manifest.json")
REQUIRED_EVIDENCE = (
    "availability",
    "worker_replay",
    "log_redaction",
    "schema_isolation",
    "correlation",
    "ci_isolation",
    "security",
)


def percentile_95(values: list[float]) -> float:
    if not values or any(value < 0 for value in values):
        raise ValueError("latency samples must be nonempty and nonnegative")
    ordered = sorted(values)
    return ordered[math.ceil(len(ordered) * 0.95) - 1]


def evaluate(report: dict, *, release_sha: str | None = None) -> dict:
    expected_book = json.loads(MANIFEST.read_text(encoding="utf-8"))["real_pilot"]["book_family"]
    if report.get("book_family") != expected_book:
        raise ValueError("golden set is not the selected FLTRP pilot")
    if release_sha is not None and report.get("release_sha") != release_sha:
        raise ValueError("golden set does not match the release SHA")
    for key in ("content_version_id", "model_version", "prompt_version"):
        if not report.get(key):
            raise ValueError(f"golden set lacks {key}")
    approval = report.get("approval") or {}
    if not approval.get("reviewer") or approval.get("decision") != "approved":
        raise ValueError("named human approval is required")
    reviewed_at = date.fromisoformat(approval["reviewed_at"])
    if reviewed_at > date.today():
        raise ValueError("approval date is in the future")
    cases = report.get("cases") or []
    if len(cases) < 20:
        raise ValueError("the golden set requires at least 20 reviewed cases")
    if report.get("ready_exercise_count") != len(cases):
        raise ValueError("every READY pilot exercise must be reviewed")
    ids = [item["id"] for item in cases]
    if len(ids) != len(set(ids)):
        raise ValueError("golden-set case ids must be unique")
    for item in cases:
        for key in (
            "schema_valid",
            "citation_valid",
            "evidence_covered",
            "answer_grounded",
            "ambiguous",
            "duplicate",
        ):
            if type(item.get(key)) is not bool:
                raise ValueError(f"case {item['id']} lacks human-reviewed {key}")
    total = len(cases)
    metrics = {
        "cases": total,
        "schema_citation_evidence_coverage": sum(
            all(item[key] for key in ("schema_valid", "citation_valid", "evidence_covered"))
            for item in cases
        )
        / total,
        "answer_key_groundedness": sum(item["answer_grounded"] for item in cases) / total,
        "duplicate_rate": sum(item["duplicate"] for item in cases) / total,
        "invalid_or_ambiguous_rate": sum(
            (not all(item[key] for key in ("schema_valid", "citation_valid", "evidence_covered")))
            or item["ambiguous"]
            for item in cases
        )
        / total,
    }
    timings = report.get("latency_ms") or {}
    for key in ("catalog_search", "resume", "generation_submit"):
        samples = timings.get(key) or []
        if len(samples) < 20:
            raise ValueError(f"{key} needs at least 20 latency samples")
        metrics[f"{key}_p95_ms"] = percentile_95(samples)
    operations = report.get("operational_evidence") or {}
    if float(operations.get("availability_percent", 0)) < 99.5:
        raise ValueError("HNFR-5 availability is below 99.5%")
    for key in REQUIRED_EVIDENCE:
        if not operations.get(key):
            raise ValueError(f"HNFR operational evidence missing: {key}")
    gates = {
        "HNFR-1": metrics["catalog_search_p95_ms"] <= 500 and metrics["resume_p95_ms"] <= 300,
        "HNFR-2": metrics["generation_submit_p95_ms"] <= 1000,
        "HNFR-3": metrics["schema_citation_evidence_coverage"] == 1,
        "HNFR-4": metrics["answer_key_groundedness"] >= 0.95
        and metrics["duplicate_rate"] <= 0.02
        and metrics["invalid_or_ambiguous_rate"] <= 0.05,
        "HNFR-5..11": True,
    }
    return {
        "book_family": expected_book,
        "reviewed_at": str(reviewed_at),
        "reviewer": approval["reviewer"],
        "metrics": metrics,
        "gates": gates,
        "passed": all(gates.values()),
    }


def main() -> None:
    parser = argparse.ArgumentParser()
    parser.add_argument("--report", type=Path, required=True)
    parser.add_argument("--release-sha")
    parser.add_argument("--output", type=Path)
    args = parser.parse_args()
    result = evaluate(
        json.loads(args.report.read_text(encoding="utf-8")), release_sha=args.release_sha
    )
    rendered = json.dumps(result, ensure_ascii=False, indent=2)
    if args.output:
        args.output.parent.mkdir(parents=True, exist_ok=True)
        args.output.write_text(rendered + "\n", encoding="utf-8")
    print(rendered)
    if not result["passed"]:
        raise SystemExit("Hiruzen golden-set release gate failed")


if __name__ == "__main__":
    main()
