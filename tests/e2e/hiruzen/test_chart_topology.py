"""Render-only acceptance: independent Practice workloads and source isolation."""

from __future__ import annotations

import shutil
import subprocess
from pathlib import Path

import pytest
import yaml

ROOT = Path(__file__).resolve().parents[3]
CHART = ROOT / "infra/k8s/course-tutor"


@pytest.mark.parametrize(
    "overlay",
    ["values-ci.yaml", "values-local-real.example.yaml", "values-production.example.yaml"],
)
def test_independent_practice_topology(overlay: str) -> None:
    helm = shutil.which("helm")
    if helm is None:
        pytest.skip("Helm is not installed on this test runner")
    rendered = subprocess.check_output(  # noqa: S603 - fixed local chart and executable
        [helm, "template", "course-tutor", str(CHART), "-f", str(CHART / overlay)],
        text=True,
    )
    resources = [item for item in yaml.safe_load_all(rendered) if item]
    indexed = {(item["kind"], item["metadata"]["name"]): item for item in resources}
    agent = indexed["Deployment", "course-tutor-backend"]
    api = indexed["Deployment", "course-tutor-practice-api"]
    worker = indexed["Deployment", "course-tutor-practice-worker"]

    def containers(workload: dict) -> list[str]:
        return [item["name"] for item in workload["spec"]["template"]["spec"]["containers"]]

    assert containers(agent) == ["agent-api"]
    assert containers(api) == ["practice-api"]
    assert containers(worker) == ["practice-worker"]
    for workload in (api, worker):
        pod = workload["spec"]["template"]["spec"]
        assert pod["securityContext"]["runAsNonRoot"] is True
        assert pod["automountServiceAccountToken"] is False
        assert all(volume["name"] != "course-content" for volume in pod["volumes"])
        assert pod["initContainers"][0]["name"] == "wait-for-practice-migration"
        container = pod["containers"][0]
        assert container["resources"]["limits"]
        assert container["readinessProbe"] and container["livenessProbe"]
        env_names = {item["name"] for item in container["env"]}
        assert "AGENT_BASE_URL" in env_names
        assert "MINIO_SECRET_KEY" not in env_names
        assert "QDRANT_URL" not in env_names
    practice_service = indexed["Service", "course-tutor-practice"]
    assert practice_service["spec"]["selector"]["app.kubernetes.io/component"] == "practice-api"
    assert ("Job", "course-tutor-practice-migrate-1") in indexed
    if overlay == "values-production.example.yaml":
        for name in ("practice-api", "practice-worker"):
            assert ("HorizontalPodAutoscaler", f"course-tutor-{name}") in indexed
            assert ("PodDisruptionBudget", f"course-tutor-{name}") in indexed
            assert ("NetworkPolicy", f"course-tutor-{name}") in indexed
        assert api["spec"]["replicas"] == 2
        assert worker["spec"]["replicas"] == 2
        for workload in (api, worker):
            for container in workload["spec"]["template"]["spec"]["containers"]:
                assert "@sha256:" in container["image"]
            database = next(
                item
                for item in workload["spec"]["template"]["spec"]["containers"][0]["env"]
                if item["name"] == "PRACTICE_POSTGRES_DSN"
            )
            assert database["valueFrom"]["secretKeyRef"]["name"] == "course-tutor-practice-db"
