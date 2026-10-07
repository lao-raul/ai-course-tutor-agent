"""Static, deterministic release-readiness checks used locally and in CI."""

from __future__ import annotations

import ast
import json
import re
from pathlib import Path

import yaml

ROOT = Path(__file__).resolve().parents[1]
WORKFLOWS = ROOT / ".github" / "workflows"
FULL_SHA = re.compile(r"^[^\s]+@[a-f0-9]{40}(?:\s+#.*)?$")


def _alembic_assignment(path: Path, name: str) -> str | None:
    tree = ast.parse(path.read_text(encoding="utf-8"), filename=str(path))
    for node in tree.body:
        if isinstance(node, ast.AnnAssign) and isinstance(node.target, ast.Name):
            if node.target.id == name and node.value is not None:
                value = ast.literal_eval(node.value)
                if value is None or isinstance(value, str):
                    return value
                raise ValueError(f"{path}: {name} must be a string or None")
    raise ValueError(f"{path}: missing {name} assignment")


def _alembic_head() -> str:
    versions = ROOT / "apps" / "api" / "alembic" / "versions"
    revisions: set[str] = set()
    parents: set[str] = set()
    for path in sorted(versions.glob("*.py")):
        revision = _alembic_assignment(path, "revision")
        if revision is None:
            raise ValueError(f"{path}: revision cannot be None")
        revisions.add(revision)
        parent = _alembic_assignment(path, "down_revision")
        if parent is not None:
            parents.add(parent)
    heads = revisions - parents
    if len(heads) != 1:
        raise ValueError(f"expected exactly one Alembic head, found {sorted(heads)}")
    return heads.pop()


def main() -> None:
    failures: list[str] = []
    for path in sorted(WORKFLOWS.glob("*.yml")):
        yaml.safe_load(path.read_text(encoding="utf-8"))
        for number, line in enumerate(path.read_text(encoding="utf-8").splitlines(), 1):
            stripped = line.strip()
            if stripped.startswith("uses:"):
                value = stripped.removeprefix("uses:").strip()
                if value.startswith("./"):
                    continue
                if not FULL_SHA.match(value):
                    failures.append(f"{path.relative_to(ROOT)}:{number}: action is not SHA-pinned")

    release = (WORKFLOWS / "release.yml").read_text(encoding="utf-8")
    deploy = (WORKFLOWS / "deploy.yml").read_text(encoding="utf-8")
    required_release = (
        "workflow_run:",
        "--provenance=mode=max",
        "cosign sign",
        "release-manifest",
        "steps.publish.outputs.agent_digest",
        "steps.publish.outputs.practice_digest",
        "steps.publish.outputs.worker_digest",
        "steps.publish.outputs.web_digest",
    )
    # The shell implementation owns the build flags and signing call.
    publish_script = (ROOT / "scripts" / "publish-release.sh").read_text(encoding="utf-8")
    combined_release = release + publish_script
    for marker in required_release:
        if marker not in combined_release:
            failures.append(f"release delivery marker missing: {marker}")
    for marker in ("environment:", "helm rollback", "scripts/deploy-release.sh"):
        if marker not in deploy:
            failures.append(f"deployment marker missing: {marker}")

    chart_values = yaml.safe_load(
        (ROOT / "infra" / "k8s" / "course-tutor" / "values.yaml").read_text(encoding="utf-8")
    )
    try:
        alembic_head = _alembic_head()
    except ValueError as exc:
        failures.append(str(exc))
    else:
        configured_revision = chart_values["config"].get("expectedAlembicRevision")
        if configured_revision != alembic_head:
            failures.append(
                "Helm expectedAlembicRevision must match the Alembic head: "
                f"expected {alembic_head}, found {configured_revision}"
            )

    dashboard = json.loads(
        (ROOT / "infra" / "observability" / "grafana-dashboard.json").read_text(encoding="utf-8")
    )
    if len(dashboard.get("panels", [])) < 6:
        failures.append("operations dashboard must retain all six required signal panels")

    if failures:
        raise SystemExit("\n".join(failures))
    print("Delivery workflows, action pins and observability assets are valid.")


if __name__ == "__main__":
    main()
