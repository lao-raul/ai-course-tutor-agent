"""Conservative lexical check for close paraphrases of an accepted objective.

The separate LLM audit still decides harder semantic cases. This guard catches
obvious rephrasings even when the model incorrectly marks them distinct.
"""

from __future__ import annotations

import re
import unicodedata
from hashlib import sha256

from course_tutor_practice.generation.schemas import GenerationObjective

_STOP_WORDS = frozenset(
    {
        "a",
        "about",
        "an",
        "and",
        "are",
        "as",
        "at",
        "by",
        "for",
        "from",
        "how",
        "in",
        "is",
        "of",
        "on",
        "the",
        "their",
        "this",
        "to",
        "using",
        "when",
        "with",
        "you",
        "your",
    }
)

_GENERIC_EXPRESSION_WORDS = frozenset(
    {"a", "am", "an", "and", "are", "i", "is", "it", "my", "the", "this", "that", "your"}
)


def answer_expression_keys(text: str) -> frozenset[str]:
    """Hash meaningful contiguous word groups, including a reply inside a longer answer.

    A single vocabulary word is not globally blocked; generic sentence frames
    such as ``this is`` are also excluded. Full-expression keys preserve exact
    matching when phrases have different pair segmentation.
    """
    normalized = unicodedata.normalize("NFKC", text).casefold()
    normalized = re.sub(r"(?<=\w)['\u2019](?=\w)", "", normalized)
    words = re.findall(r"[a-z]+|[\u4e00-\u9fff]+", normalized)
    if len(words) < 2:
        return frozenset()
    fragments: set[str] = set()
    whole = "".join(words)
    if len(whole) >= 8:
        fragments.add(whole)
    for size in range(2, min(6, len(words)) + 1):
        for start in range(len(words) - size + 1):
            segment = words[start : start + size]
            phrase = "".join(segment)
            if len(phrase) >= 6 and any(word not in _GENERIC_EXPRESSION_WORDS for word in segment):
                fragments.add(phrase)
    return frozenset(sha256(value.encode("utf-8")).hexdigest() for value in fragments)


def stored_answer_keys(objective: GenerationObjective) -> frozenset[str]:
    keys = set(objective.answer_keys)
    if objective.answer_key:
        keys.add(objective.answer_key)
    # Older accepted sets stored only one full-expression hash. Recover short
    # quoted expressions from their private objective text without touching
    # protected answer columns or rewriting immutable sets.
    without_internal_apostrophes = re.sub(
        r"(?<=\w)['\u2019](?=\w)", "", objective.learning_objective
    )
    for phrase in re.findall(
        r"(?<!\w)['\"\u201c\u2018]([^'\"\u201d\u2019]{4,})['\"\u201d\u2019](?!\w)",
        without_internal_apostrophes,
    ):
        keys.update(answer_expression_keys(phrase))
    return frozenset(keys)


def _tokens(objective: str) -> frozenset[str]:
    text = unicodedata.normalize("NFKC", objective).casefold()
    result: set[str] = set()
    for match in re.finditer(r"[a-z]+|[\u4e00-\u9fff]+", text):
        value = match.group()
        if "\u4e00" <= value[0] <= "\u9fff":
            result.update(value[index : index + 2] for index in range(len(value) - 1))
        elif value not in _STOP_WORDS:
            result.add(value)
    return frozenset(result)


def _skill_key(objective: str) -> str | None:
    """Unify high-confidence paraphrases that lexical overlap cannot catch.

    These are *skills*, not answer words: two named characters introducing
    themselves still test the same immediate learning goal, while asking for
    somebody else's name is a different skill.
    """
    text = unicodedata.normalize("NFKC", objective).casefold().replace("\u2019", "'")
    if (
        re.search(r"\bintroduc(?:e|es|ed|ing)\s+(?:oneself|yourself|themselves)\b", text)
        or re.search(r"\bself[- ]introduction\b", text)
        or re.search(
            r"\b(?:stat(?:e|es|ed|ing)|giv(?:e|es|ing)|say(?:s|ing)?|tell(?:s|ing)?)"
            r"\s+(?:one'?s|your|their)\s+(?:own\s+)?name\b",
            text,
        )
        or re.search(r"\bmy\s+name\s+is\b", text)
    ):
        return "self_introduction"
    if re.search(r"\b(?:recit(?:e|es|ed|ing)|count(?:s|ed|ing)?)\b", text) and re.search(
        r"\b(?:numerals?|numbers?|one|two|three|four|five|six|seven|eight|nine|ten)\b",
        text,
    ):
        return "number_sequence"
    if re.search(r"\bwhat(?:'s| is) your name\b", text) or (
        re.search(r"\b(?:ask(?:s|ed|ing)?|inquir(?:e|es|ed|ing)|request(?:s|ed|ing)?)\b", text)
        and re.search(r"\bname\b", text)
        and not re.search(r"\b(?:object|item|thing)\b", text)
    ):
        return "name_inquiry"
    return None


def near_duplicate_objective(left: str, right: str) -> bool:
    """Require several shared content tokens and high Jaccard overlap.

    Distinct vocabulary targets in a common sentence frame should remain
    available (e.g. ``father`` versus ``brother``).
    """
    skill = _skill_key(left)
    if skill is not None and skill == _skill_key(right):
        return True
    first = _tokens(left)
    second = _tokens(right)
    if min(len(first), len(second)) < 3:
        return False
    common = len(first & second)
    return common >= 3 and common / len(first | second) >= 0.72
