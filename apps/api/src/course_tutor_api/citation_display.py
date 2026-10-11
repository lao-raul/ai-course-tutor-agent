"""Conservative learner-facing excerpts from OCR-derived textbook chunks.

This never changes stored chunks or generation evidence. If a passage is too
noisy to quote reliably, callers show the source filename and page instead.
"""

from __future__ import annotations

import re

_SENTENCE = re.compile(r"[^.!?\u3002\uff01\uff1f]+(?:[.!?\u3002\uff01\uff1f]+|$)")
_LATIN_WORD = re.compile(r"[A-Za-z]+(?:['\u2019][A-Za-z]+)?")
_OCR_MARKS = re.compile(r"[�¢]|[—_]{2,}")


def _readable(sentence: str) -> bool:
    if not sentence or _OCR_MARKS.search(sentence):
        return False
    letters = sum(character.isalpha() for character in sentence)
    if letters < 3 or letters / len(sentence) < 0.45:
        return False
    words = _LATIN_WORD.findall(sentence)
    if words:
        capitals = sum(word.isupper() and 2 <= len(word) <= 5 for word in words)
        if (len(words) >= 6 and capitals >= 3 and capitals / len(words) >= 0.3) or (
            len(words) <= 3 and capitals >= 2 and capitals / len(words) >= 0.5
        ):
            return False
        # A fragment beginning in lower-case and abruptly switching to several
        # capitalized words is usually a broken OCR line, not a safe quote.
        if words[0][0].islower() and sum(word[:1].isupper() for word in words[1:]) >= 2:
            return False
    return True


def display_excerpt(text: str, limit: int = 240) -> str:
    """Return the longest contiguous readable sentence run, or no excerpt."""
    normalized = " ".join(text.split())
    runs: list[str] = []
    current: list[str] = []
    for match in _SENTENCE.finditer(normalized):
        sentence = match.group().strip()
        if _readable(sentence):
            current.append(sentence)
        elif current:
            runs.append(" ".join(current))
            current = []
    if current:
        runs.append(" ".join(current))
    if not runs:
        return ""
    excerpt = max(runs, key=len)
    if len(excerpt) <= limit:
        return excerpt
    prefix = excerpt[: limit - 1]
    word_end = prefix.rfind(" ")
    if word_end > limit // 2:
        prefix = prefix[:word_end]
    return prefix.rstrip() + "…"
