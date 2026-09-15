"""Delivery and operations assets remain parseable and policy-complete."""

from __future__ import annotations

from pathlib import Path

import yaml

from scripts.validate_delivery import main as validate_delivery

ROOT = Path(__file__).resolve().parents[2]


def test_delivery_validator() -> None:
    validate_delivery()


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
