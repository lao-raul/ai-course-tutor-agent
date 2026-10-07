from __future__ import annotations

from pathlib import Path

import pytest
from course_tutor_ingestion.china_textbook_catalog import (
    ChinaTextbookCatalogScanner,
    normalize_catalog_text,
    public_candidate_metadata,
)

from course_tutor_contracts.enums import CatalogCandidateStatus, EducationLevel


def _pdf(root: Path, series: str, grade: str, term: str) -> None:
    directory = root / "小学" / "英语" / series
    directory.mkdir(parents=True, exist_ok=True)
    (directory / f"义务教育教科书·英语{grade}年级{term}.pdf").write_bytes(b"%PDF-test")


def test_fltrp_pilot_scans_36_stable_review_candidates(tmp_path: Path) -> None:
    series = {
        "外研社版（一年级起点）（主编：陈琳）": "一二三四五六",
        "外研社版（三年级起点）（主编：刘兆义）": "三四五六",
        "外研社版（三年级起点）（主编：桂诗春）": "三四五六",
        "外研社版（三年级起点）（主编：陈琳）": "三四五六",
    }
    for series_name, grades in series.items():
        for grade in grades:
            for term in ("上册", "下册"):
                _pdf(tmp_path, series_name, grade, term)

    scanner = ChinaTextbookCatalogScanner(
        tmp_path,
        prefix="小学/英语",
        series_contains="外研社",
    )
    first = scanner.scan()
    second = scanner.scan()

    assert len(first.candidates) == 36
    assert first.snapshot_hash == second.snapshot_hash
    assert [item.stable_key for item in first.candidates] == [
        item.stable_key for item in second.candidates
    ]
    assert all(item.status is CatalogCandidateStatus.STAGED for item in first.candidates)
    assert all(not item.issues for item in first.candidates)
    assert {item.metadata["education_level"] for item in first.candidates} == {
        EducationLevel.PRIMARY.value
    }
    assert {item.metadata["publisher"] for item in first.candidates} == {"外研社"}
    assert {item.metadata["start_grade"] for item in first.candidates} == {"1", "3"}
    assert {item.metadata["language"] for item in first.candidates} == {"en"}


def test_ambiguous_metadata_is_quarantined_for_review(tmp_path: Path) -> None:
    _pdf(tmp_path, "自定义教材", "三", "上册")
    candidate = ChinaTextbookCatalogScanner(tmp_path).scan().candidates[0]

    assert candidate.status is CatalogCandidateStatus.NEEDS_REVIEW
    assert candidate.issues == ("publisher_unparsed",)


def test_nested_layout_requires_review(tmp_path: Path) -> None:
    path = tmp_path / "小学" / "英语" / "外研社版（三年级起点）" / "三年级"
    path.mkdir(parents=True)
    (path / "义务教育教科书·英语三年级上册.pdf").write_bytes(b"%PDF-test")

    candidate = ChinaTextbookCatalogScanner(tmp_path).scan().candidates[0]
    assert candidate.status is CatalogCandidateStatus.NEEDS_REVIEW
    assert "nested_layout_requires_review" in candidate.issues


def test_public_metadata_never_exposes_source_paths(tmp_path: Path) -> None:
    _pdf(tmp_path, "外研社版（三年级起点）（主编：陈琳）", "三", "上册")
    candidate = ChinaTextbookCatalogScanner(tmp_path).scan().candidates[0]

    rendered = public_candidate_metadata(candidate)
    assert "relative_path" not in rendered
    assert str(tmp_path) not in str(rendered)


def test_prefix_cannot_escape_corpus(tmp_path: Path) -> None:
    with pytest.raises(ValueError, match="safe relative"):
        ChinaTextbookCatalogScanner(tmp_path, prefix="../outside")


def test_hidden_directories_and_non_k12_content_are_excluded(tmp_path: Path) -> None:
    hidden = tmp_path / ".cache" / "小学" / "英语" / "外研社版"
    hidden.mkdir(parents=True)
    (hidden / "英语三年级上册.pdf").write_bytes(b"%PDF-hidden")
    university = tmp_path / "大学" / "英语" / "外研社版"
    university.mkdir(parents=True)
    (university / "大学英语上册.pdf").write_bytes(b"%PDF-university")

    assert ChinaTextbookCatalogScanner(tmp_path).scan().candidates == ()


def test_normalization_is_unicode_and_whitespace_stable() -> None:
    assert normalize_catalog_text("  英语（PEP）  ") == normalize_catalog_text("英语(PEP)")
