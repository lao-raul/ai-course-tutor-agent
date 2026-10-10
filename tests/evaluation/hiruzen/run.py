"""Deterministic fake-provider quality gate for Hiruzen's generated fixtures."""

from __future__ import annotations

import argparse
import json
from pathlib import Path
from uuid import UUID

from course_tutor_contracts import (
    ChunkClass,
    GeneratePracticeRequest,
    PracticeEvidenceChunk,
    PracticeEvidenceResponse,
)
from course_tutor_contracts.enums import AnchorType
from course_tutor_practice.application.validation import InvalidGeneration, validate_batch
from course_tutor_practice.generation.schemas import GeneratedBatch

ROOT = Path(__file__).resolve().parents[3]
MANIFEST = Path(__file__).with_name("manifest.json")


def evaluate() -> dict[str, object]:
    manifest = json.loads(MANIFEST.read_text(encoding="utf-8"))
    fixture = json.loads((ROOT / manifest["synthetic_fixture"]).read_text(encoding="utf-8"))
    if [case["name"] for case in fixture["cases"]] != manifest["synthetic_cases"]:
        raise AssertionError("fixture/manifest mismatch")
    evidence = PracticeEvidenceResponse(
        generation_id=UUID(fixture["generation_id"]),
        book_id=UUID(fixture["book_id"]),
        course_id=UUID(fixture["course_id"]),
        content_version_id=UUID(fixture["content_version_id"]),
        retrieval_trace_id=UUID(fixture["retrieval_trace_id"]),
        retrieval_policy_version="fixture-v1",
        allowed_content_classes=(ChunkClass.CONTENT,),
        solution_release_after_incorrect_attempts=3,
        chunks=(
            PracticeEvidenceChunk(
                chunk_id=UUID(fixture["chunk_id"]),
                source_id=UUID(fixture["source_id"]),
                text=fixture["evidence"],
                relative_path="synthetic-fltrp-grade3.pdf",
                anchor_type=AnchorType.PAGE,
                anchor_value="4",
                chunk_class=ChunkClass.CONTENT,
                score=0.9,
            ),
        ),
    )
    passed = 0
    prompts: set[str] = set()
    failures: list[str] = []
    for case in fixture["cases"]:
        try:
            request = GeneratePracticeRequest.model_validate(case["request"])
            batch = GeneratedBatch.model_validate({"exercises": [case["draft"]]})
            validate_batch(batch, request, evidence)
        except (ValueError, InvalidGeneration):
            failures.append(case["name"])
            continue
        passed += 1
        prompts.add(batch.exercises[0].prompt.strip().casefold())
    total = len(fixture["cases"])
    result: dict[str, object] = {
        "provider": "fake",
        "cases": total,
        "valid": passed,
        "schema_and_citation_coverage": passed / total,
        "duplicate_rate": (passed - len(prompts)) / total,
        "failures": failures,
    }
    if passed != total or len(prompts) != total:
        raise AssertionError(result)
    return result


if __name__ == "__main__":
    parser = argparse.ArgumentParser()
    parser.add_argument("--provider", choices=["fake"], default="fake")
    parser.add_argument("--output", type=Path)
    args = parser.parse_args()
    report = evaluate()
    rendered = json.dumps(report, ensure_ascii=False, indent=2)
    if args.output:
        args.output.parent.mkdir(parents=True, exist_ok=True)
        args.output.write_text(rendered + "\n", encoding="utf-8")
    print(rendered)
