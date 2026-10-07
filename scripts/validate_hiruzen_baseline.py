"""Validate the Hiruzen v0.3 requirement, task and operation baseline."""

from __future__ import annotations

import json
import re
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
FUNCTION_SPEC = ROOT / "apps/practice/docs/function_spec.md"
DESIGN_SPEC = ROOT / "apps/practice/docs/design_spec.md"
TRACEABILITY = ROOT / "apps/practice/docs/requirements-traceability.md"
TASKS = ROOT / "docs/tasks"

REQUIREMENT_PATTERN = re.compile(r"^\| ((?:HFR-[A-Z]+-\d+)|(?:HNFR-\d+)) \|")
TASK_PATTERN = re.compile(r"TASK-\d{2}")
OPERATION_PATTERN = re.compile(r"^\| `([a-z][A-Za-z0-9]+)` \|")
STATUSES = {"planned", "in_progress", "implemented"}
HIRUZEN_TASK_NUMBERS = range(18, 24)


class HiruzenBaselineError(AssertionError):
    """Raised when the accepted Hiruzen specification is inconsistent."""


def _requirements() -> set[str]:
    return {
        match.group(1)
        for line in FUNCTION_SPEC.read_text(encoding="utf-8").splitlines()
        if (match := REQUIREMENT_PATTERN.match(line))
    }


def _task_ids() -> set[str]:
    result: set[str] = set()
    for path in TASKS.glob("task-*.md"):
        result.update(TASK_PATTERN.findall(path.read_text(encoding="utf-8")))
    return result


def _operation_ids() -> set[str]:
    operations: set[str] = set()
    for path in (FUNCTION_SPEC, DESIGN_SPEC):
        operations.update(
            match.group(1)
            for line in path.read_text(encoding="utf-8").splitlines()
            if (match := OPERATION_PATTERN.match(line))
        )
    for path in (ROOT / "packages/contracts/openapi").glob("*.json"):
        document = json.loads(path.read_text(encoding="utf-8"))
        for path_item in document.get("paths", {}).values():
            for operation in path_item.values():
                if isinstance(operation, dict) and operation.get("operationId"):
                    operations.add(operation["operationId"])
    return operations


def _trace_rows() -> dict[str, tuple[str, str, str, str]]:
    rows: dict[str, tuple[str, str, str, str]] = {}
    for line in TRACEABILITY.read_text(encoding="utf-8").splitlines():
        match = REQUIREMENT_PATTERN.match(line)
        if not match:
            continue
        cells = [cell.strip() for cell in line.strip().strip("|").split("|")]
        if len(cells) != 5:
            raise HiruzenBaselineError(f"traceability row must have five columns: {line}")
        requirement, tasks, operations, verification, status = cells
        if requirement in rows:
            raise HiruzenBaselineError(f"duplicate traceability row: {requirement}")
        rows[requirement] = (tasks, operations, verification, status)
    return rows


def _validate_delivery_tasks() -> None:
    for number in HIRUZEN_TASK_NUMBERS:
        matches = list(TASKS.glob(f"task-{number:02d}-*.md"))
        if len(matches) != 1:
            raise HiruzenBaselineError(
                f"TASK-{number:02d}: expected one task document, found {len(matches)}"
            )
        text = matches[0].read_text(encoding="utf-8")
        for heading in ("## Deliverable artifacts", "## Acceptance criteria", "## Verification"):
            if heading not in text:
                raise HiruzenBaselineError(f"TASK-{number:02d}: missing {heading}")

        acceptance_ids = [
            int(value) for value in re.findall(rf"\*\*AC-{number:02d}\.(\d+):\*\*", text)
        ]
        if len(acceptance_ids) < 4 or acceptance_ids != list(range(1, len(acceptance_ids) + 1)):
            raise HiruzenBaselineError(
                f"TASK-{number:02d}: acceptance criteria must be sequential AC IDs"
            )

        artifact_section = text.split("## Deliverable artifacts", 1)[1].split(
            "## Acceptance criteria", 1
        )[0]
        artifact_rows = [
            line for line in artifact_section.splitlines() if line.startswith("|") and "`" in line
        ]
        if len(artifact_rows) < 5:
            raise HiruzenBaselineError(
                f"TASK-{number:02d}: at least five path-addressable artifacts are required"
            )


def validate() -> None:
    requirements = _requirements()
    rows = _trace_rows()
    tasks = _task_ids()
    operations = _operation_ids()
    _validate_delivery_tasks()

    if requirements != set(rows):
        missing = sorted(requirements - set(rows))
        extra = sorted(set(rows) - requirements)
        raise HiruzenBaselineError(
            f"traceability coverage mismatch; missing={missing}, extra={extra}"
        )

    for requirement, (task_cell, operation_cell, verification, status) in rows.items():
        referenced_tasks = set(TASK_PATTERN.findall(task_cell))
        unknown_tasks = referenced_tasks - tasks
        if not referenced_tasks or unknown_tasks:
            raise HiruzenBaselineError(
                f"{requirement}: missing/unknown task references: {sorted(unknown_tasks)}"
            )
        referenced_operations = {item.strip() for item in operation_cell.split(",") if item.strip()}
        unknown_operations = referenced_operations - operations
        if not referenced_operations or unknown_operations:
            raise HiruzenBaselineError(
                f"{requirement}: missing/unknown operation IDs: {sorted(unknown_operations)}"
            )
        if not verification:
            raise HiruzenBaselineError(f"{requirement}: verification is required")
        if status not in STATUSES:
            raise HiruzenBaselineError(f"{requirement}: invalid status {status!r}")

    print(
        "Hiruzen baseline valid: "
        f"{len(requirements)} requirements, {len(tasks)} tasks, {len(operations)} operations"
    )


if __name__ == "__main__":
    validate()
