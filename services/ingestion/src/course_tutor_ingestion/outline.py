"""Deterministic PDF textbook-outline extraction; never calls an LLM."""

from __future__ import annotations

import hashlib
import re
import unicodedata
from collections import Counter
from collections.abc import Iterable
from dataclasses import dataclass
from pathlib import Path
from typing import Any

EXTRACTOR_VERSION = "pdf-outline-v2"
_TITLE_LIMIT = 300


@dataclass(frozen=True, slots=True)
class OutlineNode:
    id: str
    parent_id: str | None
    ordinal: int
    title: str
    page_start: int
    page_end: int | None
    depth: int

    def as_dict(self) -> dict[str, Any]:
        return {
            "id": self.id,
            "parent_id": self.parent_id,
            "ordinal": self.ordinal,
            "title": self.title,
            "page_start": self.page_start,
            "page_end": self.page_end,
            "depth": self.depth,
        }


@dataclass(frozen=True, slots=True)
class ExtractedOutline:
    availability: str
    provenance: str
    confidence: float
    reason: str | None
    nodes: tuple[OutlineNode, ...] = ()


def _clean_title(value: object) -> str:
    title = " ".join(unicodedata.normalize("NFKC", str(value)).split())
    title = re.sub(
        r"\b(module|unit|lesson|chapter)\s*(\d+)\b",
        r"\1 \2",
        title,
        flags=re.IGNORECASE,
    )
    return title[:_TITLE_LIMIT]


def _match_line(value: object) -> str:
    """Normalize whitespace without expanding an ellipsis into three periods."""
    return " ".join(unicodedata.normalize("NFC", str(value)).split())[: _TITLE_LIMIT + 100]


def _node_id(
    source_checksum: str, ordinal: int, title: str, page: int, parent_id: str | None
) -> str:
    # The checksum makes IDs stable across retries yet prevents collisions between editions.
    raw = (
        f"{EXTRACTOR_VERSION}|{source_checksum}|{ordinal}|{parent_id or ''}|{page}|{title}".encode()
    )
    return "ol_" + hashlib.sha256(raw).hexdigest()[:24]


def _valid(nodes: list[OutlineNode]) -> bool:
    return bool(nodes) and all(node.title and node.page_start >= 1 for node in nodes)


def _make_nodes(records: list[tuple[str, int, int]], checksum: str) -> tuple[OutlineNode, ...]:
    result: list[OutlineNode] = []
    parents: dict[int, str] = {}
    for ordinal, (raw_title, raw_page, raw_depth) in enumerate(records):
        title = _clean_title(raw_title)
        page = max(1, int(raw_page))
        depth = max(0, min(8, int(raw_depth)))
        while depth and depth - 1 not in parents:
            depth -= 1
        parent_id = parents.get(depth - 1) if depth else None
        node = OutlineNode(
            _node_id(checksum, ordinal, title, page, parent_id),
            parent_id,
            ordinal,
            title,
            page,
            None,
            depth,
        )
        result.append(node)
        parents[depth] = node.id
        for key in tuple(parents):
            if key > depth:
                del parents[key]
    return tuple(result)


def _bookmark_records(reader: Any) -> list[tuple[str, int, int]]:
    raw = getattr(reader, "outline", None)
    if raw is None:
        raw = getattr(reader, "outlines", None)
    records: list[tuple[str, int, int]] = []

    def walk(items: list[Any], depth: int) -> None:
        for item in items:
            if isinstance(item, list):
                walk(item, depth + 1)
                continue
            try:
                raw_title = getattr(item, "title", None)
                if raw_title is None and hasattr(item, "get"):
                    raw_title = item.get("/Title", "")
                title = _clean_title(raw_title or "")
                page = reader.get_destination_page_number(item) + 1
            except Exception:
                continue
            if title:
                records.append((title, page, depth))

    if isinstance(raw, list):
        walk(raw, 0)
    return records


_TOC = re.compile(
    r"^(?P<title>.+?)\s*(?:[．·…]{2,}|\.{3,})\s*(?P<page>\d{1,4})$",
    re.IGNORECASE,
)
_HEADING = re.compile(
    r"^(第\s*[一二三四五六七八九十百0-9]+\s*[章节课单元].{0,200}|(?:module|unit|lesson|chapter)\s*\d+\b.{0,200}|review\s+module|\d+(?:\.\d+){0,3}\s+.{1,200})$",
    re.IGNORECASE,
)
_PARENT_HEADING = re.compile(
    r"^(?:(?:module\s*\d+)|review\s+module|第\s*[一二三四五六七八九十百0-9]+\s*(?:章|单元).*)$",
    re.IGNORECASE,
)
_CHILD_HEADING = re.compile(
    r"^(?:(?:unit|lesson)\s*\d+\b|第\s*[一二三四五六七八九十百0-9]+\s*课\b)",
    re.IGNORECASE,
)


def _page_text(page: Any, *, layout: bool) -> str:
    """Use layout extraction where supported and retain lightweight test doubles."""
    try:
        if layout:
            return page.extract_text(extraction_mode="layout") or ""
        return page.extract_text() or ""
    except TypeError:
        return page.extract_text() or ""


def _printed_page_offset(page_texts: list[str]) -> int:
    """Infer the stable printed-page to physical-PDF offset from page furniture.

    Textbook contents usually refer to printed page numbers while evidence anchors use
    one-based physical PDF pages.  Only numeric labels at the start or end of a page are
    considered, and an offset needs at least two observations, so exercise numbers do
    not silently become an offset.
    """
    candidates: list[int] = []
    page_count = len(page_texts)
    for physical_page, text in enumerate(page_texts, 1):
        lines = [_clean_title(line) for line in text.splitlines() if _clean_title(line)]
        for line in (*lines[:2], *lines[-2:]):
            if not line.isdigit():
                continue
            printed_page = int(line)
            if 1 <= printed_page <= page_count and physical_page >= printed_page:
                candidates.append(physical_page - printed_page)
    if not candidates:
        return 0
    offset, observations = Counter(candidates).most_common(1)[0]
    return offset if observations >= 2 else 0


def _anchor_page(printed_page: int, offset: int, page_count: int) -> int:
    physical_page = printed_page + offset
    return physical_page if 1 <= physical_page <= page_count else printed_page


def _text_records(reader: Any, page_count: int) -> tuple[list[tuple[str, int, int]], str, float]:
    toc: list[tuple[str, int, int]] = []
    headings: list[tuple[str, int, int]] = []
    page_texts = [_page_text(page, layout=True) for page in reader.pages]
    text_chars = sum(len(text.strip()) for text in page_texts)
    page_offset = _printed_page_offset(page_texts)
    for page_number, text in enumerate(page_texts, 1):
        pending_parent: str | None = None
        parent_written = False
        for raw_line in text.splitlines():
            line = _match_line(raw_line)
            if not line:
                continue
            match = _TOC.match(line)
            if match and 1 <= int(match.group("page")) <= page_count:
                title = _clean_title(match.group("title"))
                anchor = _anchor_page(int(match.group("page")), page_offset, page_count)
                is_child = bool(_CHILD_HEADING.match(title))
                if pending_parent is not None and is_child:
                    if not parent_written:
                        toc.append((pending_parent, anchor, 0))
                        parent_written = True
                    toc.append((title, anchor, 1))
                else:
                    toc.append((title, anchor, 0))
                    pending_parent = None
                    parent_written = False
            elif _PARENT_HEADING.match(line):
                pending_parent = _clean_title(line)
                parent_written = False
            elif _HEADING.match(line) and len(line) <= 220:
                headings.append((line, page_number, 0))
    if toc:
        return list(dict.fromkeys(toc)), "text_toc", 0.92
    # Heading rules require more than one distinct heading: one heading is not structure.
    deduped = list(dict.fromkeys(headings))
    if len(deduped) >= 2:
        return deduped, "heading_rules", 0.70
    if text_chars < 100:
        return [], "ocr", 0.0
    return [], "none", 0.0


def _ocr_records(lines: Iterable[tuple[str, int]]) -> list[tuple[str, int, int]]:
    """Derive structure only from OCR text already produced by the ingestion parser."""
    records: list[tuple[str, int, int]] = []
    for raw_line, page in lines:
        line = _match_line(raw_line)
        if not line or page < 1:
            continue
        toc = _TOC.match(line)
        if toc:
            records.append((_clean_title(toc.group("title")), int(toc.group("page")), 0))
        elif _HEADING.match(line) and len(line) <= 220:
            records.append((line, page, 0))
    return list(dict.fromkeys(records))


def extract_outline_from_reader(
    reader: Any,
    source_checksum: str,
    *,
    ocr_lines: Iterable[tuple[str, int]] = (),
) -> ExtractedOutline:
    """Extract in strict bookmark → text → OCR order from an opened PDF reader."""
    bookmarks = _make_nodes(_bookmark_records(reader), source_checksum)
    if _valid(list(bookmarks)):
        return ExtractedOutline("available", "pdf_bookmarks", 0.98, None, bookmarks)
    records, provenance, confidence = _text_records(reader, len(reader.pages))
    nodes = _make_nodes(records, source_checksum)
    if _valid(list(nodes)):
        return ExtractedOutline("available", provenance, confidence, None, nodes)
    if provenance == "ocr":
        ocr_nodes = _make_nodes(_ocr_records(ocr_lines), source_checksum)
        if _valid(list(ocr_nodes)):
            return ExtractedOutline("available", "ocr", 0.60, None, ocr_nodes)
        return ExtractedOutline("unavailable", "ocr", 0.0, "ocr_no_reliable_structure")
    return ExtractedOutline("unavailable", provenance, 0.0, "no_reliable_structure")


def extract_pdf_outline(
    path: Path,
    source_checksum: str,
    *,
    ocr_lines: Iterable[tuple[str, int]] = (),
) -> ExtractedOutline:
    """Return one safe, deterministic result for a PDF artifact.

    OCR is supplied only from the ingestion parser after it has found no reliable PDF
    text layer. This keeps the optional OCR dependency in one place and never guesses
    structure from an LLM.
    """
    try:
        from pypdf import PdfReader

        reader = PdfReader(str(path))
        return extract_outline_from_reader(reader, source_checksum, ocr_lines=ocr_lines)
    except Exception:
        # Never disclose artifact paths or raw parser failures through the catalog API.
        return ExtractedOutline("unavailable", "none", 0.0, "pdf_unreadable")
