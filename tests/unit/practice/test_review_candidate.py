"""Teacher-only review drafts never imply a human quality approval."""

from pathlib import Path

import pytest

from scripts.render_practice_review_candidate import _review_output, render_review


def test_review_draft_shows_protected_answer_and_source_but_no_approval() -> None:
    candidate = {
        "book_id": "book-1",
        "content_version_id": "version-1",
        "cases": [
            {
                "ordinal": 1,
                "module_title": "Unit 1",
                "generation_id": "job-1",
                "exercise_id": "exercise-1",
                "status": "ready",
                "question_type": "multiple_choice",
            }
        ],
    }
    details = [
        {
            "generation": {"id": "job-1"},
            "practice_set": {
                "exercises": [
                    {
                        "id": "exercise-1",
                        "type": "multiple_choice",
                        "prompt": "What is this?",
                        "options": [
                            {"id": "A", "text": "a book"},
                            {"id": "B", "text": "a desk"},
                        ],
                        "evidence_citation_ids": ["chunk-1"],
                    }
                ],
                "evidence_sources": [
                    {
                        "chunk_id": "chunk-1",
                        "relative_path": "books/Book.pdf",
                        "anchor_value": "12",
                        "text_excerpt": "It is a desk.",
                    }
                ],
            },
        }
    ]
    draft = render_review(candidate, details, {"exercise-1": {"correct_option_id": "B"}})
    assert "B: a desk" in draft
    assert "Book.pdf" in draft
    assert "物理第 12 页" in draft
    assert "待审核" in draft
    assert "批准" not in draft


def test_review_draft_must_be_gitignored(tmp_path: Path) -> None:
    with pytest.raises(ValueError, match="build/reports"):
        _review_output(tmp_path / "public.md")
