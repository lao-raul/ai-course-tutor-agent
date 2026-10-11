from __future__ import annotations

from pathlib import Path
from types import SimpleNamespace

from course_tutor_ingestion.parsers import Chunk, PDFParser
from course_tutor_ingestion.scanner import FileEntry
from course_tutor_ingestion.verified_pdf_pages import verified_page_chunks


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


def test_verified_pages_only_match_exact_source_and_page_count() -> None:
    checksum = "d8e8b67b92a5d615508aa9d950f2be35e3a435a5cdc893d423fc02e7bfb2619b"
    assert verified_page_chunks(checksum, 82) == {}
    assert verified_page_chunks("0" * 64, 83) == {}
    pages = verified_page_chunks(checksum, 83)
    assert set(pages) == {16, 34, 35, 36, 40, 41, 42, 49, 50, 51, 58}
    assert any("What's your name? I'm Sam." in chunk.text for chunk in pages[16])
    assert any("Nine girls? Oh! Ten." in chunk.text for chunk in pages[34])
    assert any("ten fingers on my hands." in chunk.text for chunk in pages[35])
    assert any("How many girls? Six!" in chunk.text for chunk in pages[36])
    assert any("How old are you, Daming? I'm nine too." in chunk.text for chunk in pages[40])
    assert any("How old are you, Maomao? B: I'm seven." in chunk.text for chunk in pages[41])
    assert any("Stand up, 2, 4, 6 and 10." in chunk.text for chunk in pages[42])
    assert any("Your cat or your kite?" in chunk.text for chunk in pages[49])
    assert any("Is it a monster? Yes, it is!" in chunk.text for chunk in pages[50])
    assert any("Is it a kite? No, it isn't." in chunk.text for chunk in pages[51])
    assert not any("It's a..." in chunk.text for chunk in pages[51])
    assert any("He's a doctor. She's a driver." in chunk.text for chunk in pages[58])


def test_verified_pages_replace_only_corrupt_ocr_pages(tmp_path: Path, monkeypatch) -> None:
    artifact = tmp_path / "book.pdf"
    artifact.write_bytes(b"x" * (84 * 10 * 1024))
    entry = FileEntry(
        relative_path="book.pdf",
        absolute_path=artifact,
        checksum="d8e8b67b92a5d615508aa9d950f2be35e3a435a5cdc893d423fc02e7bfb2619b",
        size_bytes=artifact.stat().st_size,
        mime_type="application/pdf",
        mtime_ns=0,
    )
    pages = [SimpleNamespace(extract_text=lambda: "Other page text " * 7) for _ in range(83)]
    pages[15] = SimpleNamespace(extract_text=lambda: "garbled OCR text " * 7)
    pages[33] = SimpleNamespace(extract_text=lambda: "garbled OCR text " * 7)
    pages[57] = SimpleNamespace(extract_text=lambda: "garbled OCR text " * 7)
    monkeypatch.setattr("pypdf.PdfReader", lambda _path: SimpleNamespace(pages=pages))
    result = PDFParser().parse(entry, artifact)
    page16 = [chunk.text for chunk in result.chunks if chunk.anchor_value == "16"]
    page17 = [chunk.text for chunk in result.chunks if chunk.anchor_value == "17"]
    page34 = [chunk.text for chunk in result.chunks if chunk.anchor_value == "34"]
    page58 = [chunk.text for chunk in result.chunks if chunk.anchor_value == "58"]
    page59 = [chunk.text for chunk in result.chunks if chunk.anchor_value == "59"]
    page33 = [chunk.text for chunk in result.chunks if chunk.anchor_value == "33"]
    assert result.metadata["verified_page_count"] == 11
    assert "garbled" not in " ".join(page16)
    assert "What's your name? I'm Sam." in " ".join(page16)
    assert page17 == [("Other page text " * 7).strip()]
    assert "garbled" not in " ".join(page34)
    assert "Nine girls?" in " ".join(page34)
    assert "garbled" not in " ".join(page58)
    assert "He's a doctor." in " ".join(page58)
    assert page59 == [("Other page text " * 7).strip()]
    assert page33 == [("Other page text " * 7).strip()]
