from __future__ import annotations

from pathlib import Path

from course_tutor_ingestion.jobs import _coalesce_chunks, snapshot_hash
from course_tutor_ingestion.parsers import Chunk
from course_tutor_ingestion.scanner import FileEntry


def _entry(path: str, checksum: str) -> FileEntry:
    return FileEntry(
        relative_path=path,
        absolute_path=Path("/fixture") / path,
        checksum=checksum,
        size_bytes=1,
        mime_type="text/plain",
        mtime_ns=1,
    )


def test_snapshot_detects_add_edit_delete_and_rename() -> None:
    original = [_entry("a.md", "one"), _entry("b.md", "two")]
    variants = [
        [*original, _entry("c.md", "three")],
        [_entry("a.md", "changed"), original[1]],
        [original[0]],
        [_entry("renamed.md", "one"), original[1]],
    ]
    baseline = snapshot_hash(original)
    assert all(snapshot_hash(variant) != baseline for variant in variants)
    assert snapshot_hash(list(reversed(original))) == baseline


def test_coalescing_preserves_classes_anchors_and_token_counts() -> None:
    chunks = _coalesce_chunks(
        [
            Chunk("Question one", "slide", "3", "exercise_question"),
            Chunk("Question two", "slide", "4", "exercise_question"),
            Chunk("Solution", "slide", "5", "exercise_solution"),
            Chunk("Exam item", "page", "6", "assessment"),
        ],
        target_size=1000,
    )
    assert [item.chunk_class for item in chunks] == [
        "exercise_question",
        "exercise_question",
        "exercise_solution",
        "assessment",
    ]
    assert chunks[0].anchor_type == "slide"
    assert [item.anchor_value for item in chunks] == ["3", "4", "5", "6"]
    assert all(item.token_count and item.token_count > 0 for item in chunks)


def test_coalescing_keeps_pdf_pages_as_independent_citation_units() -> None:
    chunks = _coalesce_chunks(
        [
            Chunk("Page one title", "page", "1"),
            Chunk("Page one body", "page", "1"),
            Chunk("Page two body", "page", "2"),
        ]
    )

    assert [(item.anchor_value, item.text) for item in chunks] == [
        ("1", "Page one title Page one body"),
        ("2", "Page two body"),
    ]
