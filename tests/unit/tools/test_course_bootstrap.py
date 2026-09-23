from __future__ import annotations

from pathlib import Path
from typing import Any

import pytest

from scripts.course_bootstrap import (
    ApiClient,
    BootstrapError,
    CourseMapping,
    ensure_registration,
    load_mapping,
    publish_latest_ready,
    wait_for_ingestion,
)


class StubClient(ApiClient):
    def __init__(self, responses: list[Any]) -> None:
        self.responses = iter(responses)
        self.calls: list[tuple[str, str, dict[str, Any] | None]] = []

    def request(
        self,
        method: str,
        path: str,
        body: dict[str, Any] | None = None,
        *,
        headers: dict[str, str] | None = None,
    ) -> Any:
        self.calls.append((method, path, body))
        return next(self.responses)


def mapping() -> CourseMapping:
    return CourseMapping(
        api_base_url="http://127.0.0.1:8000",
        token_env="TOKEN",
        programme_code="MSC-AI",
        programme_name="MSc AI",
        course_code="COMP-TEST",
        course_name="Test Course",
        level="postgraduate",
        run_key="2026-s1",
        source_path="/data/content/test",
        scan_interval_seconds=900,
        automatic_ingestion_enabled=True,
    )


def test_load_mapping_rejects_host_or_smb_source_path(tmp_path: Path) -> None:
    config = tmp_path / "course.yaml"
    config.write_text(
        """
api: {base_url: http://127.0.0.1:8000}
programme: {code: MSC-AI, name: MSc AI}
course:
  code: COMP
  name: Course
  level: postgraduate
  run_key: 2026
  source_path: smb://private/share
""",
        encoding="utf-8",
    )
    with pytest.raises(BootstrapError, match="in-container path"):
        load_mapping(config)


def test_existing_registration_is_reused_without_posts() -> None:
    item = mapping()
    client = StubClient(
        [
            [
                {
                    "programme_id": "programme",
                    "code": item.programme_code,
                    "name": item.programme_name,
                }
            ],
            [{"id": "course", "code": item.course_code}],
            {
                "course_id": "course",
                "course_run_id": "run",
                "source_root_id": "root",
                "programme_id": "programme",
                "code": item.course_code,
                "name": item.course_name,
                "level": item.level,
                "run_key": item.run_key,
                "resolved_path": item.source_path,
                "scan_interval_seconds": 900,
            },
        ]
    )
    result = ensure_registration(client, item)
    assert result == {
        "programme_id": "programme",
        "course_id": "course",
        "course_run_id": "run",
        "source_root_id": "root",
    }
    assert all(method == "GET" for method, _path, _body in client.calls)


def test_registration_mismatch_fails_closed() -> None:
    item = mapping()
    client = StubClient(
        [
            [{"programme_id": "programme", "name": item.programme_name}],
            [{"id": "course", "code": item.course_code}],
            {
                "programme_id": "programme",
                "code": item.course_code,
                "name": item.course_name,
                "level": item.level,
                "run_key": item.run_key,
                "resolved_path": "/data/content/a-different-module",
                "scan_interval_seconds": 900,
            },
        ]
    )
    with pytest.raises(BootstrapError, match="resolved_path"):
        ensure_registration(client, item)


def test_wait_returns_ready_and_publish_is_explicit(monkeypatch: pytest.MonkeyPatch) -> None:
    monkeypatch.setattr("scripts.course_bootstrap.time.sleep", lambda _seconds: None)
    client = StubClient(
        [
            {"status": "processed", "version_status": "building", "stats": {}},
            {"status": "processed", "version_status": "ready", "version_id": "version"},
            [{"version_id": "version", "status": "ready", "sequence": 1}],
            {"version_id": "version", "status": "published"},
        ]
    )
    status = wait_for_ingestion(
        client, "job", timeout_seconds=5, poll_seconds=0, retry_failed=False
    )
    assert status["version_status"] == "ready"
    published = publish_latest_ready(client, "course")
    assert published["status"] == "published"
    assert client.calls[-1][0] == "POST"


def test_dead_letter_reports_retry_guidance() -> None:
    client = StubClient(
        [{"status": "dead_lettered", "last_error": "unreadable source", "stats": {}}]
    )
    with pytest.raises(BootstrapError, match="--retry-failed"):
        wait_for_ingestion(client, "job", timeout_seconds=1, poll_seconds=0, retry_failed=False)
