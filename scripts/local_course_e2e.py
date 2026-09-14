#!/usr/bin/env python3
"""Validate a published local course and grounded SSE chat against the real provider."""

from __future__ import annotations

import argparse
import json
import sys
from pathlib import Path
from typing import Any
from urllib.error import HTTPError, URLError
from urllib.parse import quote, urlencode
from urllib.request import Request, urlopen

import yaml

from scripts.course_bootstrap import BootstrapError, create_client, load_mapping


def stream_events(base_url: str, token: str, course_id: str, query: str) -> list[dict[str, Any]]:
    request = Request(  # noqa: S310 -- base_url is validated as HTTP(S)
        f"{base_url.rstrip('/')}/v1/courses/{quote(course_id)}/chat",
        data=json.dumps({"query": query}).encode(),
        method="POST",
        headers={
            "Authorization": f"Bearer {token}",
            "Content-Type": "application/json",
            "Accept": "text/event-stream",
        },
    )
    events: list[dict[str, Any]] = []
    try:
        with urlopen(request, timeout=180) as response:  # noqa: S310
            event_name: str | None = None
            for raw in response:
                line = raw.decode(errors="replace").strip()
                if line.startswith("event:"):
                    event_name = line.removeprefix("event:").strip()
                elif line.startswith("data:") and event_name:
                    events.append(
                        {
                            "event": event_name,
                            "data": json.loads(line.removeprefix("data:").strip()),
                        }
                    )
                    event_name = None
    except HTTPError as exc:
        raise BootstrapError(f"chat failed ({exc.code}): {exc.read().decode()}") from exc
    except URLError as exc:
        raise BootstrapError(f"chat endpoint is unreachable: {exc.reason}") from exc
    return events


def _question_config(path: Path) -> tuple[str, str]:
    raw = yaml.safe_load(path.read_text(encoding="utf-8"))
    e2e = raw.get("e2e", {}) if isinstance(raw, dict) else {}
    if not isinstance(e2e, dict) or not e2e.get("in_scope_question"):
        raise BootstrapError("config requires e2e.in_scope_question")
    return str(e2e["in_scope_question"]), str(
        e2e.get("out_of_scope_question", "What is today's weather on Mars?")
    )


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--config", type=Path, required=True)
    args = parser.parse_args(argv)
    try:
        mapping = load_mapping(args.config)
        client = create_client(mapping)
        token = client.token
        in_scope, out_of_scope = _question_config(args.config)
        courses = client.request("GET", "/v1/courses")
        course = next((item for item in courses if item["code"] == mapping.course_code), None)
        if course is None:
            raise BootstrapError("registered course is absent from GET /v1/courses")
        version_id = course.get("active_content_version_id")
        if not version_id:
            raise BootstrapError("course has no active published content version")
        source_query = urlencode({"version_id": version_id})
        sources = client.request(
            "GET", f"/v1/admin/courses/{quote(course['id'])}/sources?{source_query}"
        )
        source_paths = {item["relative_path"] for item in sources}

        grounded = stream_events(mapping.api_base_url, token, course["id"], in_scope)
        event_names = [item["event"] for item in grounded]
        citations = [item["data"] for item in grounded if item["event"] == "citation"]
        if "token" not in event_names or "done" not in event_names or not citations:
            raise BootstrapError(f"grounded chat lacked tokens/citation/done: {event_names}")
        if any(item["relative_path"] not in source_paths for item in citations):
            raise BootstrapError("chat emitted a citation outside the active content version")

        unrelated = stream_events(mapping.api_base_url, token, course["id"], out_of_scope)
        if "abstained" not in [item["event"] for item in unrelated]:
            raise BootstrapError("unrelated question did not follow the abstention policy")
        print(
            json.dumps(
                {
                    "course_id": course["id"],
                    "active_content_version_id": version_id,
                    "citation_count": len(citations),
                    "grounded_chat": "passed",
                    "abstention": "passed",
                },
                indent=2,
                sort_keys=True,
            )
        )
        return 0
    except (BootstrapError, OSError, yaml.YAMLError) as exc:
        print(f"local-course-e2e: {exc}", file=sys.stderr)
        return 1


if __name__ == "__main__":
    raise SystemExit(main())
