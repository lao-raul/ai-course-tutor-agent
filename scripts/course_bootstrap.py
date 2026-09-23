#!/usr/bin/env python3
"""Idempotently register, ingest and explicitly publish one mapped course."""

from __future__ import annotations

import argparse
import json
import os
import sys
import time
import uuid
from dataclasses import dataclass
from pathlib import Path
from typing import Any
from urllib.error import HTTPError, URLError
from urllib.parse import quote, urlencode
from urllib.request import Request, urlopen

import yaml


class BootstrapError(RuntimeError):
    """Actionable operator error that is safe to print."""


@dataclass(frozen=True)
class CourseMapping:
    api_base_url: str
    token_env: str
    programme_code: str
    programme_name: str
    course_code: str
    course_name: str
    level: str
    run_key: str
    source_path: str
    scan_interval_seconds: int
    automatic_ingestion_enabled: bool


class ApiClient:
    def __init__(self, base_url: str, token: str, *, timeout: float = 30.0) -> None:
        self.base_url = base_url.rstrip("/")
        self.token = token
        self.timeout = timeout

    def request(
        self,
        method: str,
        path: str,
        body: dict[str, Any] | None = None,
        *,
        headers: dict[str, str] | None = None,
    ) -> Any:
        payload = None if body is None else json.dumps(body).encode()
        request = Request(  # noqa: S310 -- base_url is validated as HTTP(S)
            self.base_url + path,
            data=payload,
            method=method,
            headers={
                "Authorization": f"Bearer {self.token}",
                "Accept": "application/json",
                **({"Content-Type": "application/json"} if payload is not None else {}),
                **(headers or {}),
            },
        )
        try:
            with urlopen(request, timeout=self.timeout) as response:  # noqa: S310
                raw = response.read()
                return json.loads(raw) if raw else None
        except HTTPError as exc:
            detail = exc.read().decode(errors="replace")
            raise BootstrapError(f"{method} {path} failed ({exc.code}): {detail}") from exc
        except URLError as exc:
            raise BootstrapError(
                f"Agent API is unreachable at {self.base_url}: {exc.reason}"
            ) from exc


def _required(mapping: dict[str, Any], key: str, section: str) -> Any:
    value = mapping.get(key)
    if value is None or value == "":
        raise BootstrapError(f"missing config value: {section}.{key}")
    return value


def load_mapping(path: Path) -> CourseMapping:
    if not path.is_file():
        raise BootstrapError(f"config does not exist: {path}")
    try:
        raw = yaml.safe_load(path.read_text(encoding="utf-8"))
    except yaml.YAMLError as exc:
        raise BootstrapError(f"invalid YAML in {path}: {exc}") from exc
    if not isinstance(raw, dict):
        raise BootstrapError("config root must be a mapping")
    sections: dict[str, dict[str, Any]] = {}
    for name in ("api", "programme", "course"):
        value = raw.get(name)
        if not isinstance(value, dict):
            raise BootstrapError(f"config section {name} must be a mapping")
        sections[name] = value
    api, programme, course = sections["api"], sections["programme"], sections["course"]
    source_path = str(_required(course, "source_path", "course"))
    if not source_path.startswith("/") or "://" in source_path:
        raise BootstrapError("course.source_path must be an absolute in-container path")
    base_url = str(_required(api, "base_url", "api")).rstrip("/")
    if not base_url.startswith(("http://", "https://")):
        raise BootstrapError("api.base_url must be an HTTP(S) URL")
    return CourseMapping(
        api_base_url=base_url,
        token_env=str(api.get("token_env", "COURSE_TUTOR_AUTH_TOKEN")),
        programme_code=str(_required(programme, "code", "programme")),
        programme_name=str(_required(programme, "name", "programme")),
        course_code=str(_required(course, "code", "course")),
        course_name=str(_required(course, "name", "course")),
        level=str(_required(course, "level", "course")),
        run_key=str(_required(course, "run_key", "course")),
        source_path=source_path,
        scan_interval_seconds=int(course.get("scan_interval_seconds", 900)),
        automatic_ingestion_enabled=bool(course.get("automatic_ingestion_enabled", True)),
    )


def create_client(mapping: CourseMapping) -> ApiClient:
    token = os.environ.get(mapping.token_env)
    if not token:
        raise BootstrapError(
            f"authentication token environment variable is unset: {mapping.token_env}"
        )
    return ApiClient(mapping.api_base_url, token)


def ensure_registration(client: ApiClient, mapping: CourseMapping) -> dict[str, str]:
    programmes = client.request(
        "GET", f"/v1/admin/programmes?{urlencode({'code': mapping.programme_code})}"
    )
    if programmes:
        programme = programmes[0]
        if programme["name"] != mapping.programme_name:
            raise BootstrapError("programme code exists with different metadata")
        programme_id = programme["programme_id"]
    else:
        programme_id = client.request(
            "POST",
            "/v1/admin/programmes",
            {"code": mapping.programme_code, "name": mapping.programme_name},
        )["programme_id"]

    courses = client.request("GET", "/v1/courses")
    matches = [course for course in courses if course["code"] == mapping.course_code]
    if matches:
        course_id = matches[0]["id"]
        detail = client.request("GET", f"/v1/admin/courses/{quote(course_id)}/registration")
        expected = {
            "programme_id": programme_id,
            "code": mapping.course_code,
            "name": mapping.course_name,
            "level": mapping.level,
            "run_key": mapping.run_key,
            "resolved_path": mapping.source_path,
            "scan_interval_seconds": mapping.scan_interval_seconds,
        }
        mismatches = [key for key, value in expected.items() if detail.get(key) != value]
        if mismatches:
            raise BootstrapError(
                "course code exists with different registration fields: " + ", ".join(mismatches)
            )
    else:
        detail = client.request(
            "POST",
            "/v1/admin/courses",
            {
                "programme_id": programme_id,
                "code": mapping.course_code,
                "name": mapping.course_name,
                "level": mapping.level,
                "run_key": mapping.run_key,
                "source_path": mapping.source_path,
                "scan_interval_seconds": mapping.scan_interval_seconds,
                "automatic_ingestion_enabled": mapping.automatic_ingestion_enabled,
            },
        )
        course_id = detail["course_id"]
    return {
        "programme_id": programme_id,
        "course_id": course_id,
        "course_run_id": detail["course_run_id"],
        "source_root_id": detail["source_root_id"],
    }


def wait_for_ingestion(
    client: ApiClient,
    job_id: str,
    *,
    timeout_seconds: int,
    poll_seconds: float,
    retry_failed: bool,
) -> dict[str, Any]:
    deadline = time.monotonic() + timeout_seconds
    retried = False
    while time.monotonic() < deadline:
        status = client.request("GET", f"/v1/admin/ingestions/{quote(job_id)}")
        if status["status"] == "dead_lettered":
            if retry_failed and not retried:
                client.request("POST", f"/v1/admin/ingestions/{quote(job_id)}/retry")
                retried = True
                continue
            raise BootstrapError(
                f"ingestion {job_id} is dead-lettered: {status.get('last_error')}; "
                f"retry with --retry-failed after correcting the source/provider"
            )
        if status.get("version_status") in {"ready", "published"}:
            return status
        if status["status"] == "processed" and status.get("stats", {}).get("no_change"):
            return status
        time.sleep(poll_seconds)
    raise BootstrapError(
        f"ingestion {job_id} did not become READY in {timeout_seconds}s; "
        "inspect GET /v1/admin/ingestions/{job_id} and worker logs"
    )


def publish_latest_ready(client: ApiClient, course_id: str) -> dict[str, Any]:
    versions = client.request("GET", f"/v1/admin/courses/{quote(course_id)}/versions")
    ready = next((item for item in versions if item["status"] == "ready"), None)
    if ready is None:
        current = next((item for item in versions if item["status"] == "published"), None)
        if current is not None:
            return {"already_published": True, **current}
        raise BootstrapError("course has no READY content version; run --ingest --wait first")
    return client.request(
        "POST",
        f"/v1/admin/courses/{quote(course_id)}/versions/{quote(ready['version_id'])}/publish",
    )


def parse_args(argv: list[str] | None = None) -> argparse.Namespace:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--config", type=Path, required=True)
    parser.add_argument("--ingest", action="store_true")
    parser.add_argument("--wait", action="store_true")
    parser.add_argument("--publish", action="store_true")
    parser.add_argument("--retry-failed", action="store_true")
    parser.add_argument("--timeout", type=int, default=900)
    parser.add_argument("--poll-seconds", type=float, default=2.0)
    return parser.parse_args(argv)


def main(argv: list[str] | None = None) -> int:
    args = parse_args(argv)
    try:
        mapping = load_mapping(args.config)
        client = create_client(mapping)
        result: dict[str, Any] = {"registration": ensure_registration(client, mapping)}
        course_id = result["registration"]["course_id"]
        if args.ingest:
            queued = client.request(
                "POST",
                f"/v1/admin/courses/{quote(course_id)}/ingestions",
                headers={"Idempotency-Key": f"bootstrap-{uuid.uuid4()}"},
            )
            result["ingestion"] = queued
            if args.wait:
                result["ingestion"] = wait_for_ingestion(
                    client,
                    queued["job_id"],
                    timeout_seconds=args.timeout,
                    poll_seconds=args.poll_seconds,
                    retry_failed=args.retry_failed,
                )
        elif args.wait:
            raise BootstrapError("--wait requires --ingest")
        if args.publish:
            result["publication"] = publish_latest_ready(client, course_id)
        print(json.dumps(result, indent=2, sort_keys=True))
        return 0
    except BootstrapError as exc:
        print(f"course-bootstrap: {exc}", file=sys.stderr)
        return 1


if __name__ == "__main__":
    raise SystemExit(main())
