from __future__ import annotations

from pathlib import Path
from types import SimpleNamespace

from course_tutor_ingestion.parsers import Chunk, PDFParser
from course_tutor_ingestion.scanner import FileEntry


def test_mixed_pdf_ocr_recovers_only_sparse_lesson_pages(
    tmp_path: Path,
    monkeypatch,
) -> None:
    artifact = tmp_path / "book.pdf"
    artifact.write_bytes(b"x" * (40 * 1024))
    entry = FileEntry(
        relative_path="book.pdf",
        absolute_path=artifact,
        checksum="a" * 64,
        size_bytes=artifact.stat().st_size,
        mime_type="application/pdf",
        mtime_ns=0,
    )
    pages = [
        SimpleNamespace(extract_text=lambda: "Contents " * 20),
        SimpleNamespace(extract_text=lambda: ""),
        SimpleNamespace(extract_text=lambda: "Index " * 20),
    ]
    monkeypatch.setattr("pypdf.PdfReader", lambda _path: SimpleNamespace(pages=pages))
    seen: list[int] = []

    def ocr(_path: Path, _entry: FileEntry, page_numbers: list[int]):
        seen.extend(page_numbers)
        return {2: [Chunk("Hello, I'm Sam.", "page", "2")]}

    monkeypatch.setattr(PDFParser, "_ocr_pages", staticmethod(ocr))
    result = PDFParser().parse(entry, artifact)
    assert seen == [2]
    assert result.metadata["ocr_page_count"] == 1
    assert any(chunk.anchor_value == "2" and "Sam" in chunk.text for chunk in result.chunks)
