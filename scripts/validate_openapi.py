"""Validate checked-in OpenAPI documents and outline DTO schema parity."""

from __future__ import annotations

import json
from pathlib import Path
from typing import Any

from course_tutor_contracts import (
    CatalogBookOutline,
    CatalogOutlineNode,
    PracticeEvidenceChunk,
    PracticeEvidenceRequest,
    PracticeEvidenceResponse,
)

ROOT = Path(__file__).resolve().parents[1]
OPENAPI_DIR = ROOT / "packages/contracts/openapi"
HTTP_METHODS = {"get", "post", "put", "patch", "delete", "options", "head", "trace"}


class OpenAPIValidationError(AssertionError):
    """The checked-in API contract is malformed or inconsistent."""


def _resolve_ref(document: dict[str, Any], reference: str) -> None:
    if not reference.startswith("#/"):
        raise OpenAPIValidationError(f"external reference is not allowed: {reference}")
    current: Any = document
    for token in reference.removeprefix("#/").split("/"):
        key = token.replace("~1", "/").replace("~0", "~")
        if not isinstance(current, dict) or key not in current:
            raise OpenAPIValidationError(f"unresolved reference: {reference}")
        current = current[key]


def _validate_document(path: Path) -> dict[str, Any]:
    document = json.loads(path.read_text(encoding="utf-8"))
    if not str(document.get("openapi", "")).startswith("3.1."):
        raise OpenAPIValidationError(f"{path.name}: OpenAPI 3.1.x is required")
    operation_ids: set[str] = set()

    def walk(value: Any) -> None:
        if isinstance(value, dict):
            reference = value.get("$ref")
            if isinstance(reference, str):
                _resolve_ref(document, reference)
            for child in value.values():
                walk(child)
        elif isinstance(value, list):
            for child in value:
                walk(child)

    walk(document)
    for route, item in document.get("paths", {}).items():
        if not route.startswith("/") or not isinstance(item, dict):
            raise OpenAPIValidationError(f"{path.name}: invalid route {route!r}")
        for method, operation in item.items():
            if method not in HTTP_METHODS:
                continue
            operation_id = operation.get("operationId")
            if not operation_id or operation_id in operation_ids:
                raise OpenAPIValidationError(
                    f"{path.name}: missing or duplicate operationId {operation_id!r}"
                )
            if not operation.get("responses"):
                raise OpenAPIValidationError(f"{operation_id}: responses are required")
            operation_ids.add(operation_id)
    return document


def _validate_outline_parity(agent_document: dict[str, Any]) -> None:
    schemas = agent_document["components"]["schemas"]
    expected = {
        "CatalogBookOutline": set(CatalogBookOutline.model_json_schema().get("required", [])),
        "CatalogOutlineNode": set(CatalogOutlineNode.model_json_schema().get("required", [])),
        "PracticeEvidenceRequest": set(
            PracticeEvidenceRequest.model_json_schema().get("required", [])
        ),
        "PracticeEvidenceChunk": set(PracticeEvidenceChunk.model_json_schema().get("required", [])),
        "PracticeEvidenceResponse": set(
            PracticeEvidenceResponse.model_json_schema().get("required", [])
        ),
    }
    for name, required in expected.items():
        actual = set(schemas[name].get("required", []))
        if actual != required:
            raise OpenAPIValidationError(
                f"{name}: required fields differ from DTO; expected={sorted(required)}, "
                f"actual={sorted(actual)}"
            )


def validate() -> None:
    documents = {path.name: _validate_document(path) for path in sorted(OPENAPI_DIR.glob("*.json"))}
    _validate_outline_parity(documents["agent-api.v1.json"])
    print(f"OpenAPI valid: {len(documents)} documents; outline DTO parity confirmed")


if __name__ == "__main__":
    validate()
