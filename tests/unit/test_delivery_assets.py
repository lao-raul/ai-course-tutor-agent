"""Delivery and operations assets remain parseable and policy-complete."""

from __future__ import annotations

from pathlib import Path

import yaml

from scripts.validate_delivery import main as validate_delivery

ROOT = Path(__file__).resolve().parents[2]


def test_delivery_validator() -> None:
    validate_delivery()


def test_internal_object_store_uses_one_pinned_public_registry_image() -> None:
    expected = "chrislusf/seaweedfs:4.47"
    compose_paths = (
        ROOT / "infra/docker/docker-compose.test.yml",
        ROOT / "infra/docker/docker-compose.yml",
        ROOT / "infra/docker/docker-compose.dev.yml",
    )
    for path in compose_paths:
        compose = yaml.safe_load(path.read_text(encoding="utf-8"))
        assert compose["services"]["minio"]["image"] == expected

    values = yaml.safe_load(
        (ROOT / "infra/k8s/course-tutor/values.yaml").read_text(encoding="utf-8")
    )
    assert values["internalDependencies"]["minio"]["image"] == expected


def test_internal_object_store_runs_an_s3_gateway() -> None:
    compose = yaml.safe_load(
        (ROOT / "infra/docker/docker-compose.test.yml").read_text(encoding="utf-8")
    )
    service = compose["services"]["minio"]
    assert "-s3" in service["command"]
    assert "-s3.port=9000" in service["command"]
    assert service["environment"] == {
        "AWS_ACCESS_KEY_ID": "course-tutor",
        "AWS_SECRET_ACCESS_KEY": "course-tutor-test-secret",
    }


def test_alert_rules_cover_required_incidents() -> None:
    rules = yaml.safe_load(
        (ROOT / "infra" / "observability" / "prometheus-rules.yaml").read_text(encoding="utf-8")
    )
    alerts = {
        rule["alert"]
        for group in rules["spec"]["groups"]
        for rule in group["rules"]
        if "alert" in rule
    }
    assert {
        "CourseTutorLMStudioUnavailable",
        "CourseTutorIngestionBacklog",
        "CourseTutorIngestionDeadLetter",
        "CourseTutorRetrievalEmptyRatioHigh",
        "CourseTutorDatabaseSaturation",
        "CourseTutorRolloutFailed",
    }.issubset(alerts)
