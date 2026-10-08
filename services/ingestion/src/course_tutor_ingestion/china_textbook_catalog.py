"""ChinaTextbook catalog scanning and review-stage import.

This module belongs to Agent ingestion. It never publishes a Book directly: filesystem
metadata is untrusted input and is first persisted as an immutable import candidate for
admin review/approval.
"""

from __future__ import annotations

import asyncio
import hashlib
import json
import os
import re
import unicodedata
import uuid
from dataclasses import dataclass
from datetime import UTC, datetime
from pathlib import Path, PurePosixPath
from typing import Any
from uuid import UUID

from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession

from course_tutor_api.db import CatalogImportBatch, CatalogImportCandidate
from course_tutor_contracts.enums import (
    CatalogCandidateStatus,
    CatalogImportStatus,
    EducationLevel,
)

_LEVELS: tuple[tuple[str, EducationLevel], ...] = (
    ("小学", EducationLevel.PRIMARY),
    ("初中", EducationLevel.MIDDLE_SCHOOL),
    ("高中", EducationLevel.HIGH_SCHOOL),
)
_CHINESE_GRADES = {
    "一": "1",
    "二": "2",
    "三": "3",
    "四": "4",
    "五": "5",
    "六": "6",
    "七": "7",
    "八": "8",
    "九": "9",
}
_START_GRADE_RE = re.compile(r"[（(]([一二三四五六七八九])年级起点[）)]")
_EDITOR_RE = re.compile(r"[（(]主编[：:]\s*([^）)]+)[）)]")
_GRADE_RE = re.compile(r"([一二三四五六七八九])年级")
_TERM_RE = re.compile(r"(上册|下册|全一册)")
_PUBLISHER_RE = re.compile(r"^(.+?)版(?:[（(]|$)")


def normalize_catalog_text(value: str) -> str:
    """Return a stable Unicode/search representation without changing display text."""
    return " ".join(unicodedata.normalize("NFKC", value).strip().split()).casefold()


def _sha256(path: Path) -> str:
    digest = hashlib.sha256()
    with path.open("rb") as stream:
        for block in iter(lambda: stream.read(1024 * 1024), b""):
            digest.update(block)
    return digest.hexdigest()


def _identity_key(metadata: dict[str, str | None]) -> str:
    identity_fields = (
        "education_level",
        "subject",
        "publisher",
        "series",
        "start_grade",
        "editor",
        "grade",
        "term",
        "title",
    )
    canonical = {key: normalize_catalog_text(metadata.get(key) or "") for key in identity_fields}
    encoded = json.dumps(canonical, ensure_ascii=False, sort_keys=True).encode()
    return f"china-textbook:{hashlib.sha256(encoded).hexdigest()[:32]}"


@dataclass(frozen=True, slots=True)
class CatalogCandidate:
    stable_key: str
    relative_path: str
    checksum: str
    size_bytes: int
    metadata: dict[str, str | None]
    issues: tuple[str, ...]

    @property
    def status(self) -> CatalogCandidateStatus:
        if self.issues:
            return CatalogCandidateStatus.NEEDS_REVIEW
        return CatalogCandidateStatus.STAGED


@dataclass(frozen=True, slots=True)
class CatalogScanResult:
    candidates: tuple[CatalogCandidate, ...]
    snapshot_hash: str
    selection: dict[str, str]


class ChinaTextbookCatalogScanner:
    """Read K-12 PDF metadata from a selected ChinaTextbook subtree."""

    def __init__(
        self,
        root: Path,
        *,
        prefix: PurePosixPath | str = ".",
        series_contains: str | None = None,
    ) -> None:
        self._root = root.resolve()
        self._prefix = PurePosixPath(prefix)
        self._series_contains = series_contains
        if self._prefix.is_absolute() or ".." in self._prefix.parts:
            raise ValueError("catalog prefix must be a safe relative path")

    def scan(self) -> CatalogScanResult:
        if not self._root.is_dir():
            raise ValueError("ChinaTextbook root must be an existing directory")
        scan_root = (self._root / Path(*self._prefix.parts)).resolve()
        if not scan_root.is_relative_to(self._root) or not scan_root.is_dir():
            raise ValueError("catalog selection must stay inside the ChinaTextbook root")

        paths: list[Path] = []
        for dirpath, dirnames, filenames in os.walk(scan_root):
            dirnames[:] = sorted(
                name for name in dirnames if not name.startswith(".") and name not in {"__MACOSX"}
            )
            paths.extend(
                Path(dirpath) / filename
                for filename in sorted(filenames)
                if not filename.startswith(".") and Path(filename).suffix.casefold() == ".pdf"
            )

        candidates: list[CatalogCandidate] = []
        for path in paths:
            if path.is_symlink() or not path.is_file():
                continue
            resolved = path.resolve()
            if not resolved.is_relative_to(self._root):
                continue
            relative_path = resolved.relative_to(self._root).as_posix()
            parts = PurePosixPath(relative_path).parts
            if len(parts) < 4:
                continue
            if self._series_contains and self._series_contains not in parts[2]:
                continue
            candidate = self._candidate(resolved, parts)
            if candidate is not None:
                candidates.append(candidate)

        candidates.sort(key=lambda item: item.relative_path)
        snapshot = hashlib.sha256()
        for candidate in candidates:
            snapshot.update(candidate.relative_path.encode())
            snapshot.update(b"\0")
            snapshot.update(candidate.checksum.encode())
            snapshot.update(b"\0")
            snapshot.update(candidate.stable_key.encode())
            snapshot.update(b"\n")
        selection = {"prefix": self._prefix.as_posix()}
        if self._series_contains:
            selection["series_contains"] = self._series_contains
        return CatalogScanResult(tuple(candidates), snapshot.hexdigest(), selection)

    def _candidate(self, path: Path, parts: tuple[str, ...]) -> CatalogCandidate | None:
        level_name, subject, series = parts[:3]
        level = next((value for prefix, value in _LEVELS if level_name.startswith(prefix)), None)
        if level is None:
            return None  # ChinaTextbook-only first release excludes university/other trees.

        title = path.stem
        issues: list[str] = []
        if len(parts) != 4:
            issues.append("nested_layout_requires_review")

        publisher_match = _PUBLISHER_RE.search(series)
        publisher = publisher_match.group(1) if publisher_match else None
        if publisher is None:
            issues.append("publisher_unparsed")

        grade_match = _GRADE_RE.search(title)
        grade = _CHINESE_GRADES.get(grade_match.group(1)) if grade_match else None
        if grade is None:
            issues.append("grade_unparsed")

        term_match = _TERM_RE.search(title)
        term = term_match.group(1) if term_match else None
        if term is None:
            issues.append("term_unparsed")

        start_match = _START_GRADE_RE.search(series) or _START_GRADE_RE.search(title)
        start_grade = _CHINESE_GRADES.get(start_match.group(1)) if start_match else None
        editor_match = _EDITOR_RE.search(series)
        editor = editor_match.group(1).strip() if editor_match else None
        metadata: dict[str, str | None] = {
            "education_level": level.value,
            "education_level_display": level_name,
            "subject": subject,
            "publisher": publisher,
            "series": series,
            "edition": series,
            "start_grade": start_grade,
            "editor": editor,
            "grade": grade,
            "term": term,
            "title": title,
            "normalized_title": normalize_catalog_text(title),
            "language": "en" if subject == "英语" else "zh-CN",
        }
        return CatalogCandidate(
            stable_key=_identity_key(metadata),
            relative_path=PurePosixPath(*parts).as_posix(),
            checksum=_sha256(path),
            size_bytes=path.stat().st_size,
            metadata=metadata,
            issues=tuple(sorted(set(issues))),
        )


async def stage_catalog_import(
    session: AsyncSession,
    *,
    tenant_id: UUID,
    source_root_id: UUID,
    scanner: ChinaTextbookCatalogScanner,
) -> CatalogImportBatch:
    """Persist one immutable review batch, reusing an identical prior snapshot."""
    result = await asyncio.to_thread(scanner.scan)
    existing = await session.scalar(
        select(CatalogImportBatch).where(
            CatalogImportBatch.source_root_id == source_root_id,
            CatalogImportBatch.snapshot_hash == result.snapshot_hash,
        )
    )
    if existing is not None:
        return existing

    now = datetime.now(UTC).replace(tzinfo=None)
    needs_review = sum(
        candidate.status is CatalogCandidateStatus.NEEDS_REVIEW for candidate in result.candidates
    )
    batch = CatalogImportBatch(
        id=uuid.uuid4(),
        tenant_id=tenant_id,
        source_root_id=source_root_id,
        selection=result.selection,
        snapshot_hash=result.snapshot_hash,
        status=CatalogImportStatus.STAGED,
        candidate_count=len(result.candidates),
        needs_review_count=needs_review,
        failure_reason=None,
        completed_at=now,
    )
    session.add(batch)
    session.add_all(
        [
            CatalogImportCandidate(
                id=uuid.uuid4(),
                batch_id=batch.id,
                stable_key=candidate.stable_key,
                relative_path=candidate.relative_path,
                checksum=candidate.checksum,
                size_bytes=candidate.size_bytes,
                metadata_=dict(candidate.metadata),
                status=candidate.status,
                issues=list(candidate.issues),
                imported_book_id=None,
            )
            for candidate in result.candidates
        ]
    )
    return batch


def public_candidate_metadata(candidate: CatalogCandidate) -> dict[str, Any]:
    """Return review metadata with no host path or NAS credential surface."""
    return {
        "stable_key": candidate.stable_key,
        "metadata": dict(candidate.metadata),
        "status": candidate.status.value,
        "issues": list(candidate.issues),
    }
