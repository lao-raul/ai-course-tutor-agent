"""Validate the v0.2 requirements, task and OpenAPI baseline using stdlib only."""

from __future__ import annotations

import json
import re
from pathlib import Path
from typing import Any

ROOT = Path(__file__).resolve().parents[1]
FUNCTION_SPEC = ROOT / "docs/function-spec.md"
TRACEABILITY = ROOT / "docs/requirements-traceability.md"
TASKS = ROOT / "docs/tasks"
OPENAPI_DIR = ROOT / "packages/contracts/openapi"

REQUIREMENT_PATTERN = re.compile(r"^\| ((?:FR-\d+\.\d+)|(?:NFR-\d+)) \|")
TASK_PATTERN = re.compile(r"TASK-\d{2}")
HTTP_METHODS = {"get", "post", "put", "patch", "delete", "options", "head", "trace"}
IMPLEMENTATION_STATUSES = {"implemented", "partial", "planned"}


class BaselineError(AssertionError):
    """Raised when the checked-in specification baseline is inconsistent."""


def _requirements(path: Path) -> set[str]:
    return {
        match.group(1)
        for line in path.read_text(encoding="utf-8").splitlines()
        if (match := REQUIREMENT_PATTERN.match(line))
    }


def _task_ids() -> set[str]:
    result: set[str] = set()
    for path in TASKS.glob("task-*.md"):
        result.update(TASK_PATTERN.findall(path.read_text(encoding="utf-8")))
    return result


def _resolve_local_ref(document: dict[str, Any], ref: str) -> None:
    if not ref.startswith("#/"):
        raise BaselineError(f"external OpenAPI reference is not allowed in baseline: {ref}")
    current: Any = document
    for token in ref.removeprefix("#/").split("/"):
        key = token.replace("~1", "/").replace("~0", "~")
        if not isinstance(current, dict) or key not in current:
            raise BaselineError(f"unresolved OpenAPI reference: {ref}")
        current = current[key]


def _validate_local_refs(document: dict[str, Any]) -> None:
    def walk(value: Any) -> None:
        if isinstance(value, dict):
            if "$ref" in value:
                _resolve_local_ref(document, value["$ref"])
            for child in value.values():
                walk(child)
        elif isinstance(value, list):
            for child in value:
                walk(child)

    walk(document)


def _openapi_operations() -> set[str]:
    operation_ids: set[str] = set()
    for path in sorted(OPENAPI_DIR.glob("*.json")):
        document = json.loads(path.read_text(encoding="utf-8"))
        if not str(document.get("openapi", "")).startswith("3.1."):
            raise BaselineError(f"{path.name}: expected OpenAPI 3.1.x")
        if not document.get("info", {}).get("title") or not document.get("paths"):
            raise BaselineError(f"{path.name}: info.title and paths are required")

        for route, path_item in document["paths"].items():
            if not route.startswith("/") or not isinstance(path_item, dict):
                raise BaselineError(f"{path.name}: invalid path item {route!r}")
            for method, operation in path_item.items():
                if method not in HTTP_METHODS:
                    continue
                operation_id = operation.get("operationId")
                if not operation_id:
                    raise BaselineError(f"{path.name}: {method.upper()} {route} lacks operationId")
                if operation_id in operation_ids:
                    raise BaselineError(f"duplicate operationId: {operation_id}")
                operation_ids.add(operation_id)
                status = operation.get("x-implementation-status")
                if status not in IMPLEMENTATION_STATUSES:
                    raise BaselineError(
                        f"{operation_id}: x-implementation-status must be one of "
                        f"{sorted(IMPLEMENTATION_STATUSES)}"
                    )
                if not operation.get("responses"):
                    raise BaselineError(f"{operation_id}: responses are required")

        _validate_local_refs(document)

    if not operation_ids:
        raise BaselineError("no OpenAPI operations found")
    return operation_ids


def _trace_rows() -> dict[str, tuple[str, str, str, str]]:
    rows: dict[str, tuple[str, str, str, str]] = {}
    for line in TRACEABILITY.read_text(encoding="utf-8").splitlines():
        match = REQUIREMENT_PATTERN.match(line)
        if not match:
            continue
        cells = [cell.strip() for cell in line.strip().strip("|").split("|")]
        if len(cells) != 5:
            raise BaselineError(f"traceability row must have five columns: {line}")
        requirement, tasks, operations, verification, status = cells
        if requirement in rows:
            raise BaselineError(f"duplicate traceability row: {requirement}")
        rows[requirement] = (tasks, operations, verification, status)
    return rows


def validate() -> None:
    spec_requirements = _requirements(FUNCTION_SPEC)
    trace_rows = _trace_rows()
    task_ids = _task_ids()
    operation_ids = _openapi_operations()

    if spec_requirements != set(trace_rows):
        missing = sorted(spec_requirements - set(trace_rows))
        extra = sorted(set(trace_rows) - spec_requirements)
        raise BaselineError(f"traceability coverage mismatch; missing={missing}, extra={extra}")

    for requirement, (tasks, operations, verification, status) in trace_rows.items():
        referenced_tasks = set(TASK_PATTERN.findall(tasks))
        unknown_tasks = referenced_tasks - task_ids
        if not referenced_tasks or unknown_tasks:
            raise BaselineError(
                f"{requirement}: missing/unknown task references: {sorted(unknown_tasks)}"
            )
        referenced_operations = {item.strip() for item in operations.split(",") if item.strip()}
        unknown_operations = referenced_operations - operation_ids
        if not referenced_operations or unknown_operations:
            raise BaselineError(
                f"{requirement}: missing/unknown operation IDs: {sorted(unknown_operations)}"
            )
        if not verification or not status:
            raise BaselineError(f"{requirement}: verification and status are required")

    print(
        "contract baseline valid: "
        f"{len(spec_requirements)} requirements, {len(task_ids)} tasks, "
        f"{len(operation_ids)} operations"
    )


if __name__ == "__main__":
    validate()
