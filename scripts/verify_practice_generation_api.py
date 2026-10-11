"""Generate a real PracticeSet through HTTP and audit the learner-facing response."""

from __future__ import annotations

import argparse
import json
import os
import time
import unicodedata
from pathlib import Path
from typing import Any, cast
from urllib.error import HTTPError, URLError
from urllib.parse import urlsplit
from urllib.request import Request, urlopen
from uuid import uuid4

from course_tutor_practice.application.validation import (
    has_fill_in_blank_placeholder,
    has_unverified_dialogue_pairing,
    is_true_false_statement,
)


def request_json(
    base_url: str, path: str, token: str, body: dict[str, Any] | None = None
) -> dict[str, Any]:
    target = urlsplit(base_url)
    if target.scheme not in {"http", "https"} or not target.hostname:
        raise ValueError("API base URL must be an HTTP(S) address")
    data = json.dumps(body, ensure_ascii=False).encode() if body is not None else None
    headers = {"Authorization": f"Bearer {token}"}
    if body is not None:
        headers["Content-Type"] = "application/json"
        headers["Idempotency-Key"] = str(uuid4())
    request = Request(  # noqa: S310 - scheme and host are validated above
        f"{base_url.rstrip('/')}/v1/practice{path}",
        data=data,
        headers=headers,
        method="POST" if body is not None else "GET",
    )
    try:
        with urlopen(request, timeout=30) as response:  # noqa: S310
            return cast(dict[str, Any], json.load(response))
    except HTTPError as exc:
        detail = exc.read(2048).decode("utf-8", errors="replace")
        raise RuntimeError(f"API HTTP {exc.code}: {detail}") from exc
    except URLError as exc:
        raise RuntimeError(f"API connection failed: {exc.reason}") from exc


def audit_practice_set(practice_set: dict[str, Any], count: int) -> list[str]:
    exercises = practice_set.get("exercises", [])
    sources = {item["chunk_id"] for item in practice_set.get("evidence_sources", [])}
    errors: list[str] = []
    if len(exercises) != count:
        errors.append(f"expected {count} exercises, received {len(exercises)}")
    if [item.get("ordinal") for item in exercises] != list(range(len(exercises))):
        errors.append("exercise ordinals are not contiguous")
    fingerprints: set[str] = set()
    for item in exercises:
        position = item.get("ordinal", "?")
        prompt = str(item.get("prompt", ""))
        fingerprint = " ".join(unicodedata.normalize("NFKC", prompt).casefold().split())
        if not prompt.strip():
            errors.append(f"exercise {position}: empty prompt")
        if fingerprint in fingerprints:
            errors.append(f"exercise {position}: exact duplicate prompt")
        fingerprints.add(fingerprint)
        if item.get("type") == "true_false" and not is_true_false_statement(prompt):
            errors.append(f"exercise {position}: true_false prompt is not a complete claim")
        if item.get("type") == "fill_in_the_blank" and not has_fill_in_blank_placeholder(prompt):
            errors.append(f"exercise {position}: fill_in_the_blank prompt has no blank")
        if has_unverified_dialogue_pairing(prompt):
            errors.append(f"exercise {position}: unverified dialogue pairing")
        citation_ids = item.get("evidence_citation_ids") or []
        if not citation_ids:
            errors.append(f"exercise {position}: no evidence citation")
        for citation_id in citation_ids:
            if citation_id not in sources:
                errors.append(f"exercise {position}: unresolved citation {citation_id}")
    return errors


def write_report(output: Path, report: dict[str, Any]) -> None:
    output.parent.mkdir(parents=True, exist_ok=True)
    flags = os.O_WRONLY | os.O_CREAT | os.O_EXCL
    descriptor = os.open(output, flags, 0o600)
    with os.fdopen(descriptor, "w", encoding="utf-8") as handle:
        json.dump(report, handle, ensure_ascii=False, indent=2)
        handle.write("\n")


def run(args: argparse.Namespace) -> int:
    token = os.environ.get("COURSE_TUTOR_AUTH_TOKEN", "")
    if not token:
        raise ValueError("COURSE_TUTOR_AUTH_TOKEN is required; it is never written to the report")
    request_json(args.base_url, f"/catalog/books/{args.book_id}/study-plan", token)
    job = request_json(
        args.base_url,
        f"/catalog/books/{args.book_id}/generations",
        token,
        {
            "count": args.count,
            "difficulty": args.difficulty,
            "language": args.language,
            "question_types": args.question_types
            or [
                "multiple_choice",
                "true_false",
                "fill_in_the_blank",
                "short_answer",
            ],
            **({"module_id": args.module_id} if args.module_id else {}),
        },
    )
    deadline = time.monotonic() + args.timeout
    while job.get("status") not in {"ready", "failed", "cancelled"}:
        if time.monotonic() >= deadline:
            raise TimeoutError(f"generation {job['id']} did not finish within {args.timeout}s")
        time.sleep(min(2, max(0, deadline - time.monotonic())))
        job = request_json(args.base_url, f"/generations/{job['id']}", token)
    practice_set = None
    errors = []
    if job["status"] == "ready" and job.get("practice_set_id"):
        practice_set = request_json(args.base_url, f"/sets/{job['practice_set_id']}", token)
        errors = audit_practice_set(practice_set, args.count)
    else:
        errors = [f"generation ended as {job['status']}: {job.get('error_code')}"]
    output = args.output or Path("build/reports") / f"practice-generation-{job['id']}.json"
    report = {"generation": job, "practice_set": practice_set, "audit_errors": errors}
    write_report(output, report)
    print(f"Generation {job['id']}: {job['status']}; report: {output}")
    if practice_set is not None:
        true_false_count = sum(item["type"] == "true_false" for item in practice_set["exercises"])
        print(
            f"Exercises: {len(practice_set['exercises'])}; "
            f"true/false: {true_false_count}; "
            f"audit errors: {len(errors)}"
        )
    for error in errors:
        print(f"FAIL {error}")
    if not errors:
        print("PASS API generation response audit (human quality review still required)")
    return 1 if errors else 0


def main() -> None:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--base-url", default="http://127.0.0.1:28001")
    parser.add_argument("--book-id", required=True)
    parser.add_argument("--module-id")
    parser.add_argument("--count", type=int, default=20, choices=range(1, 21))
    parser.add_argument("--language", choices=("zh", "en", "bilingual"), default="zh")
    parser.add_argument(
        "--question-type",
        dest="question_types",
        action="append",
        choices=("multiple_choice", "true_false", "fill_in_the_blank", "short_answer"),
    )
    parser.add_argument(
        "--difficulty", choices=("introductory", "standard", "challenge"), default="standard"
    )
    parser.add_argument("--timeout", type=int, default=600)
    parser.add_argument("--output", type=Path)
    args = parser.parse_args()
    raise SystemExit(run(args))


if __name__ == "__main__":
    main()
