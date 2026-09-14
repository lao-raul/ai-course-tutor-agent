"""Canonical Unit/Week scope extraction shared by indexing and retrieval."""

from __future__ import annotations

import re

_CONTENT_SCOPE_PATTERN = re.compile(
    r"(?<![a-z0-9])(?P<kind>unit|week)[\s_/-]*(?P<number>\d+)(?!\d)",
    re.IGNORECASE,
)


def extract_content_scopes(value: str) -> tuple[str, ...]:
    """Return distinct canonical scopes such as ``unit:2`` or ``week:2``.

    Keeping the scope kind is important: Unit 2 and Week 2 are separate pieces of
    course organisation and must never be treated as interchangeable.
    """

    scopes: list[str] = []
    for match in _CONTENT_SCOPE_PATTERN.finditer(value.replace("\\", "/")):
        scope = f"{match.group('kind').lower()}:{int(match.group('number'))}"
        if scope not in scopes:
            scopes.append(scope)
    return tuple(scopes)


__all__ = ["extract_content_scopes"]
