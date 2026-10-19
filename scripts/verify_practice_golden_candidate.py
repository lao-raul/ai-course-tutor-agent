"""Create an unselected 20-Unit real-book candidate for human quality review.

This is a diagnostic sample, not a signed release-gate approval. Reports contain
learner-visible textbook excerpts and must remain in the gitignored build directory.
"""

from __future__ import annotations

import argparse
import os
import re
import sys
import time
from pathlib import Path
from typing import Any
from urllib.parse import urlencode

if not __package__:
    # Also support `python scripts/verify_practice_golden_candidate.py` from a checkout.
    sys.path.insert(0, str(Path(__file__).resolve().parent.parent))

from scripts.verify_practice_generation_api import audit_practice_set, request_json, write_report

QUESTION_TYPES = (
    "multiple_choice",
    "true_false",
    "fill_in_the_blank",
    "short_answer",
)
UNIT_COUNT = 20


def select_units(plan: dict[str, Any]) -> list[dict[str, Any]]:
    """Use the first 20 named Unit 1/2 nodes; exclude undifferentiated review pages."""
    units = [
        module
        for module in plan.get("modules", [])
        if re.match(r"^Unit [12] \S", str(module.get("title", "")))
    ]
    if len(units) != UNIT_COUNT:
        raise ValueError(f"expected {UNIT_COUNT} named Units, found {len(units)}")
    return units


def run(args: argparse.Namespace) -> int:
    token = os.environ.get("COURSE_TUTOR_AUTH_TOKEN", "")
    if not token:
        raise ValueError("COURSE_TUTOR_AUTH_TOKEN is required and never saved")
    plan = request_json(args.base_url, f"/catalog/books/{args.book_id}/study-plan", token)
    units = select_units(plan)
    search_path = f"/catalog/books?{urlencode({'q': '英语', 'limit': 20})}"
    request_json(args.base_url, search_path, token)  # Exclude first-time cache warm-up.
    request_json(args.base_url, "/resume", token)
    latency_ms: dict[str, list[float]] = {
        "catalog_search": [],
        "resume": [],
        "generation_submit": [],
    }
    cases: list[dict[str, Any]] = []
    report: dict[str, Any] = {
        "book_id": args.book_id,
        "content_version_id": plan["content_version_id"],
        "selection_rule": "first 20 named Unit 1/2 nodes, one question each",
        "question_types": list(QUESTION_TYPES),
        "human_approved": False,
        "complete": False,
        "latency_ms": latency_ms,
        "latency_profile": "20 sequential LAN HTTP samples after one search/resume warm-up",
        "cases": cases,
    }
    for index, unit in enumerate(units, start=1):
        question_type = QUESTION_TYPES[(index - 1) % len(QUESTION_TYPES)]
        start = time.perf_counter()
        request_json(args.base_url, search_path, token)
        latency_ms["catalog_search"].append(round((time.perf_counter() - start) * 1000, 3))
        start = time.perf_counter()
        request_json(args.base_url, "/resume", token)
        latency_ms["resume"].append(round((time.perf_counter() - start) * 1000, 3))
        start = time.perf_counter()
        job = request_json(
            args.base_url,
            f"/catalog/books/{args.book_id}/generations",
            token,
            {
                "count": 1,
                "difficulty": "standard",
                "language": "zh",
                "question_types": [question_type],
                "module_id": unit["id"],
            },
        )
        latency_ms["generation_submit"].append(round((time.perf_counter() - start) * 1000, 3))
        deadline = time.monotonic() + args.timeout
        while job.get("status") not in {"ready", "failed", "cancelled"}:
            if time.monotonic() >= deadline:
                raise TimeoutError(f"generation {job['id']} exceeded {args.timeout}s")
            time.sleep(min(2, max(0, deadline - time.monotonic())))
            job = request_json(args.base_url, f"/generations/{job['id']}", token)
        practice_set = None
        errors = [f"generation {job['status']}: {job.get('error_code')}"]
        if job["status"] == "ready" and job.get("practice_set_id"):
            practice_set = request_json(args.base_url, f"/sets/{job['practice_set_id']}", token)
            errors = audit_practice_set(practice_set, 1)
        detail_path = args.output.parent / f"practice-generation-{job['id']}.json"
        write_report(
            detail_path,
            {"generation": job, "practice_set": practice_set, "audit_errors": errors},
        )
        exercise = (practice_set or {}).get("exercises", [{}])[0]
        cases.append(
            {
                "ordinal": index,
                "module_id": unit["id"],
                "module_title": unit["title"],
                "question_type": question_type,
                "generation_id": job["id"],
                "status": job["status"],
                "practice_set_id": job.get("practice_set_id"),
                "exercise_id": exercise.get("id"),
                "prompt": exercise.get("prompt"),
                "audit_errors": errors,
                "detail_report": str(detail_path),
            }
        )
        # Preserve the complete fixed prefix if the run is interrupted. A
        # partial diagnostic is never mistaken for a 20-case acceptance pass.
        partial_output = args.output.with_name(
            f"{args.output.stem}-partial-{index:02d}{args.output.suffix}"
        )
        write_report(partial_output, report)
        print(
            f"{index}/{UNIT_COUNT} {unit['title']}: {job['status']}; errors={len(errors)}",
            flush=True,
        )
    report["complete"] = True
    write_report(args.output, report)
    passed = all(case["status"] == "ready" and not case["audit_errors"] for case in cases)
    print(f"Candidate report: {args.output}; automated_pass={passed}")
    return 0 if passed else 1


def main() -> None:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--base-url", default="http://127.0.0.1:28001")
    parser.add_argument("--book-id", required=True)
    parser.add_argument("--timeout", type=int, default=600)
    parser.add_argument(
        "--output", type=Path, default=Path("build/reports/practice-golden-candidate.json")
    )
    raise SystemExit(run(parser.parse_args()))


if __name__ == "__main__":
    main()
