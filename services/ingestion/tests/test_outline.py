from __future__ import annotations

import json
from pathlib import Path

from course_tutor_ingestion.outline import (
    EXTRACTOR_VERSION,
    _make_nodes,
    extract_outline_from_reader,
    extract_pdf_outline,
)


class _Page:
    def __init__(self, text: str) -> None:
        self._text = text

    def extract_text(self) -> str:
        return self._text


class _Reader:
    def __init__(self, pages: list[str], outline: list[object] | None = None) -> None:
        self.pages = [_Page(text) for text in pages]
        self.outline = outline or []

    @staticmethod
    def get_destination_page_number(item: object) -> int:
        return int(getattr(item, "page", 0))


class _Bookmark:
    def __init__(self, title: str, page: int) -> None:
        self.title = title
        self.page = page


def test_outline_node_ids_and_hierarchy_are_deterministic() -> None:
    records = [("Unit 1", 3, 0), ("Lesson 1", 4, 1), ("Unit 2", 9, 0)]
    first = _make_nodes(records, "a" * 64)
    second = _make_nodes(records, "a" * 64)

    assert first == second
    assert first[1].parent_id == first[0].id
    assert [node.page_start for node in first] == [3, 4, 9]


def test_bookmarks_take_precedence_over_text_rules() -> None:
    reader = _Reader(
        ["1 Competing text heading .... 2"],
        [_Bookmark("Unit 1", 1), [_Bookmark("Lesson 1", 2)]],
    )

    outline = extract_outline_from_reader(reader, "b" * 64)

    assert outline.provenance == "pdf_bookmarks"
    assert [node.title for node in outline.nodes] == ["Unit 1", "Lesson 1"]
    assert outline.nodes[1].parent_id == outline.nodes[0].id


def test_text_toc_precedes_heading_rules() -> None:
    reader = _Reader(["1 Unit One .... 2", "Unit 2"], [])

    outline = extract_outline_from_reader(reader, "c" * 64)

    assert outline.availability == "available"
    assert outline.provenance == "text_toc"
    assert outline.nodes[0].page_start == 2


def test_ocr_is_used_only_after_no_reliable_text_layer() -> None:
    reader = _Reader(["", ""], [])

    outline = extract_outline_from_reader(
        reader,
        "d" * 64,
        ocr_lines=[("Unit 1", 1), ("Unit 2", 2)],
    )

    assert outline.availability == "available"
    assert outline.provenance == "ocr"
    assert [node.page_start for node in outline.nodes] == [1, 2]


def test_ocr_is_not_used_when_a_text_layer_has_no_reliable_structure() -> None:
    reader = _Reader(["A readable paragraph without an authored heading. " * 4], [])

    outline = extract_outline_from_reader(
        reader,
        "e" * 64,
        ocr_lines=[("Unit 1", 1), ("Unit 2", 2)],
    )

    assert outline.availability == "unavailable"
    assert outline.provenance == "none"
    assert outline.reason == "no_reliable_structure"


def test_parser_failure_does_not_expose_artifact_path(tmp_path: Path) -> None:
    artifact = tmp_path / "private-textbook.pdf"
    artifact.write_bytes(b"not-a-pdf")

    outline = extract_pdf_outline(artifact, "e" * 64)

    assert outline.availability == "unavailable"
    assert outline.reason == "pdf_unreadable"
    assert str(artifact) not in repr(outline)


def _fltrp_layout_reader() -> _Reader:
    pages = [""] * 83
    pages[4] = """
Module1
Unit 1 I’m Sam. ……………………………… 2
Unit 2 How are you? ……………………… 5
Module2
Unit 1 I’m Ms Smart. ……………………… 8
Unit 2 What’s your name? ………………… 11
Module3
Unit 1 Point to the door. ………………… 14
Unit 2 Point to the desk. ………………… 17
Module4
Unit 1 It’s red! ……………………………… 20
Unit 2 It’s a black dog. …………………… 23
Module5
Unit 1 How many? …………………………… 26
Unit 2 Nine girls? …………………………… 29
Module6
Unit 1 Happy birthday! …………………… 32
Unit 2 How old are you? …………………… 35
Module7
Unit 1 What’s this? ………………………… 38
Unit 2 What’s that? ………………………… 41
"""
    pages[5] = """
Module8
Unit 1 Is it a monster? …………………… 44
Unit 2 Where’s the cat? …………………… 47
Module9
Unit 1 This is my mother. ………………… 50
Unit 2 He’s a doctor. ……………………… 53
Module10
Unit 1 This is his head. …………………… 56
Unit 2 Point to her nose. ………………… 59
Review Module
Unit 1 …………………………………………… 62
Unit 2 …………………………………………… 64
Words and Expressions in Each Module …… 66
Word List ………………………………………… 68
Words in Songs, Chants and Rhymes ………… 71
Names ……………………………………………… 71
Reading for Pleasure
The Three Bears ………………………………… 72
Project
Word Poster ……………………………………… 74
"""
    # Two independent printed page labels establish physical = printed + 5.
    pages[10] = "6\nlesson content"
    pages[16] = "12\nlesson content"
    return _Reader(pages)


def test_fltrp_manifest_exactly_matches_reviewer_approved_structure() -> None:
    path = (
        Path(__file__).parents[3]
        / "tests/fixtures/hiruzen/outlines/fltrp-chen-lin-grade-3-first-term.json"
    )
    manifest = json.loads(path.read_text(encoding="utf-8"))
    first = extract_outline_from_reader(_fltrp_layout_reader(), "f" * 64)
    replay = extract_outline_from_reader(_fltrp_layout_reader(), "f" * 64)

    assert first == replay
    assert manifest["extractor_version"] == EXTRACTOR_VERSION
    assert manifest["reviewer_result"] == "available_approved"
    assert first.availability == manifest["availability"] == "available"
    assert first.provenance == manifest["provenance"] == "text_toc"
    assert first.confidence == manifest["confidence"]
    assert [
        {"title": node.title, "page_start": node.page_start, "depth": node.depth}
        for node in first.nodes
    ] == manifest["nodes"]
