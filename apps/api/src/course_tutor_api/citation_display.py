"""Conservative learner-facing excerpts from OCR-derived textbook chunks.

This never changes stored chunks or generation evidence. If a passage is too
noisy to quote reliably, callers show the source filename and page instead.
"""

from __future__ import annotations

import re

_SENTENCE = re.compile(r"[^.!?\u3002\uff01\uff1f]+(?:[.!?\u3002\uff01\uff1f]+|$)")
_LATIN_WORD = re.compile(r"[A-Za-z]+(?:['\u2019][A-Za-z]+)?")
_OCR_MARKS = re.compile(r"\\?\[_+\]\]+|[�¢§%®©]|[—_]{2,}")
_ACTIVITY_LABEL = re.compile(
    r"\blisten(?:,|\s+(?:and|point))|"
    r"\b(?:look and|read and|do and say|practise|practice|"
    r"unit\s+\d+|module\s+\d+)\b",
    re.IGNORECASE,
)
_OCR_LEADING_CODE = re.compile(r"^[\s\"'\u2018\u2019]*(?:\d+[A-Z]\s|#\s*\d+\s)")


def _sentence_candidate(sentence: str) -> str:
    """Keep only a verbatim suffix after a clearly corrupt OCR prefix."""
    marker = list(_OCR_MARKS.finditer(sentence))
    if not marker:
        return sentence
    candidate = sentence[marker[-1].end() :].lstrip(" =:;'\"\u2018\u2019\t")
    # A stray single word after an OCR marker is too easy to misattribute.
    return candidate if len(_LATIN_WORD.findall(candidate)) >= 3 else ""


def _repeated_phrase(words: list[str]) -> bool:
    lowered = [word.casefold() for word in words]
    return any(
        lowered[index : index + width] == lowered[index + width : index + 2 * width]
        for width in (2, 3)
        for index in range(len(lowered) - 2 * width + 1)
    )


def _readable(sentence: str) -> bool:
    if (
        not sentence
        or _OCR_MARKS.search(sentence)
        or _ACTIVITY_LABEL.search(sentence)
        or _OCR_LEADING_CODE.search(sentence)
    ):
        return False
    letters = sum(character.isalpha() for character in sentence)
    if letters < 3 or letters / len(sentence) < 0.45:
        return False
    words = _LATIN_WORD.findall(sentence)
    if words:
        if sentence[0].islower() or _repeated_phrase(words):
            return False
        if any(re.search(r"[a-z]{4,}[A-Z]", word) for word in words):
            return False
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
    readable_count = 0
    for match in _SENTENCE.finditer(normalized):
        sentence = _sentence_candidate(match.group().strip())
        if _readable(sentence):
            current.append(sentence)
            readable_count += 1
        elif current:
            runs.append(" ".join(current))
            current = []
    if current:
        runs.append(" ".join(current))
    if not runs:
        return ""
    # Several noisy regions mixed with multiple sentences usually mean that
    # OCR has reordered speech bubbles or columns. Do not present that as one
    # continuous quotation even if the individual sentences are legible.
    if len(_OCR_MARKS.findall(normalized)) >= 2 and readable_count > 1:
        return ""
    excerpt = max(runs, key=len)
    if len(excerpt) <= limit:
        return excerpt
    prefix = excerpt[: limit - 1]
    word_end = prefix.rfind(" ")
    if word_end > limit // 2:
        prefix = prefix[:word_end]
    return prefix.rstrip() + "…"


def display_fragments(text: str, limit: int = 240) -> tuple[str, ...]:
    """Return separate verbatim OCR sentences when their reading order is uncertain."""
    normalized = " ".join(text.split())
    if len(_OCR_MARKS.findall(normalized)) < 2:
        return ()
    fragments: list[str] = []
    previous_was_unit_label = False
    total = 0
    for match in _SENTENCE.finditer(normalized):
        raw = match.group().strip()
        if re.fullmatch(r"Unit\s+\d+[.]", raw, re.IGNORECASE):
            previous_was_unit_label = True
            continue
        candidate = _sentence_candidate(raw)
        if (
            not previous_was_unit_label
            and _readable(candidate)
            and 12 <= len(candidate) <= 120
            and candidate.casefold() not in {item.casefold() for item in fragments}
            and total + len(candidate) <= limit
        ):
            fragments.append(candidate)
            total += len(candidate)
            if len(fragments) == 4:
                break
        previous_was_unit_label = False
    return tuple(fragments)
