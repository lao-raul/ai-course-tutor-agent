"""Static, deterministic release-readiness checks used locally and in CI."""

from __future__ import annotations

import json
import re
from pathlib import Path

import yaml

ROOT = Path(__file__).resolve().parents[1]
WORKFLOWS = ROOT / ".github" / "workflows"
FULL_SHA = re.compile(r"^[^\s]+@[a-f0-9]{40}(?:\s+#.*)?$")


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
