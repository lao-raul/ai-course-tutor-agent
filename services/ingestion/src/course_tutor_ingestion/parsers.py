"""Document parsers.

Each parser is a callable that receives a :class:`FileEntry` and a resolved artifact
path (for MinIO-backed artifacts) and returns a list of :class:`ParsedDocument`.

Parsers are registered by MIME type in ``PARSER_REGISTRY``. All parsers return the same
shape, so the extraction pipeline is format-agnostic at the call site.
"""

from __future__ import annotations

import re
from abc import ABC, abstractmethod
from dataclasses import dataclass, field
from pathlib import Path

import structlog
from docx.text.paragraph import Paragraph

from course_tutor_ingestion.scanner import FileEntry

logger = structlog.get_logger(__name__)


@dataclass(frozen=True, slots=True)
class Chunk:
    text: str
    anchor_type: str
    anchor_value: str
    chunk_class: str = "content"
    token_count: int | None = None  # filled by jobs.py before DB write


@dataclass
class ParsedDocument:
    """Extraction result from one source file.

    ``chunks`` is ordered and retains the document's reading order.
    ``metadata`` carries whatever the format exposes (page count, slide count, headings,
    etc.) so callers can make routing or display decisions without re-opening the file.
    """

    file_entry: FileEntry = field()
    chunks: list[Chunk] = field(default_factory=list)
    metadata: dict[str, object] = field(default_factory=dict)
    extraction_status: str = "extracted"
    extraction_confidence: float | None = None
    failure_reason: str | None = None


# --- Base parser ---------------------------------------------------------------


class Parser(ABC):
    """Override ``parse`` to implement format-specific extraction."""

    mime_types: tuple[str, ...] = ()

    def __call__(self, entry: FileEntry, artifact_path: Path) -> ParsedDocument:
        try:
            return self.parse(entry, artifact_path)
        except Exception as exc:
            logger.error(
                "parser_failed",
                path=entry.relative_path,
                mime=entry.mime_type,
                exc=str(exc),
            )
            return ParsedDocument(
                file_entry=entry,
                chunks=[],
                extraction_status="failed",
                failure_reason=f"{type(exc).__name__}: {exc}",
            )

    @abstractmethod
    def parse(self, entry: FileEntry, artifact_path: Path) -> ParsedDocument: ...


# --- PDF -----------------------------------------------------------------------


# Minimum extracted chars across all pages below which we consider a PDF "empty" and
# fall back to OCR.  Scanned PDFs typically yield < 100 chars total.
_PDF_TEXT_THRESHOLD = 100


class PDFParser(Parser):
    """Extract text from PDF by page, with heading detection and OCR fallback."""

    mime_types = ("application/pdf",)

    def parse(self, entry: FileEntry, artifact_path: Path) -> ParsedDocument:
        from pypdf import PdfReader

        reader = PdfReader(str(artifact_path))
        chunks: list[Chunk] = []
        total_chars = 0

        for page_num, page in enumerate(reader.pages, start=1):
            text = page.extract_text() or ""
            total_chars += len(text)
            if not text.strip():
                continue
            lines = text.split("\n")
            for line in lines:
                stripped = line.strip()
                if not stripped:
                    continue
                chunk_class = self._classify_line(stripped)
                chunks.append(
                    Chunk(
                        text=stripped,
                        anchor_type="page",
                        anchor_value=str(page_num),
                        chunk_class=chunk_class,
                    )
                )

        # OCR fallback: file is large (> 10 KB per page expected) but pypdf found
        # almost no text → likely a scanned PDF.
        file_size = artifact_path.stat().st_size
        page_count = len(reader.pages)
        expected_min_size = page_count * 10 * 1024  # 10 KB/page heuristic
        if total_chars < _PDF_TEXT_THRESHOLD and file_size > expected_min_size:
            logger.info(
                "pdf_ocr_fallback",
                path=entry.relative_path,
                total_chars=total_chars,
                file_size=file_size,
            )
            ocr_chunks, ocr_confidence = self._ocr_pages(artifact_path, entry)
            if ocr_chunks:
                chunks.extend(ocr_chunks)
                return ParsedDocument(
                    file_entry=entry,
                    chunks=chunks,
                    metadata={
                        "page_count": page_count,
                        "ocr": True,
                    },
                    extraction_confidence=ocr_confidence,
                )
            else:
                # OCR also failed → quarantine.
                return ParsedDocument(
                    file_entry=entry,
                    chunks=[],
                    extraction_status="quarantined",
                    failure_reason="pypdf extracted no text and OCR also failed",
                    metadata={"page_count": page_count},
                )

        return ParsedDocument(
            file_entry=entry,
            chunks=chunks,
            metadata={
                "page_count": len(reader.pages),
            },
            extraction_confidence=0.95,
        )

    @staticmethod
    def _ocr_pages(artifact_path: Path, entry: FileEntry) -> tuple[list[Chunk], float]:
        """Convert PDF pages to images and run Tesseract OCR.

        Returns a list of chunks and the estimated confidence (0.70 for OCR).
        Returns an empty list if pytesseract or pdf2image are unavailable.
        """
        try:
            import pytesseract
            from pdf2image import convert_from_path
        except ImportError:
            logger.warning("pdf_ocr_import_missing", path=entry.relative_path)
            return [], 0.0

        try:
            images = convert_from_path(str(artifact_path), dpi=200)
        except Exception as exc:
            logger.warning("pdf_ocr_image_convert_failed", path=entry.relative_path, exc=str(exc))
            return [], 0.0

        chunks: list[Chunk] = []
        for page_num, image in enumerate(images, start=1):
            try:
                text = pytesseract.image_to_string(image, timeout=30)
            except Exception as exc:
                logger.warning(
                    "pdf_ocr_page_failed",
                    path=entry.relative_path,
                    page=page_num,
                    exc=str(exc),
                )
                continue
            for line in text.split("\n"):
                stripped = line.strip()
                if not stripped:
                    continue
                chunks.append(
                    Chunk(
                        text=stripped,
                        anchor_type="page",
                        anchor_value=str(page_num),
                        chunk_class="content",
                    )
                )
        return chunks, 0.70

    @staticmethod
    def _classify_line(line: str) -> str:
        # Simple heuristic: short all-caps lines are likely section headings.
        if len(line) < 80 and line.isupper():
            return "content"  # Treat as content; heading boundary detection is caller-side.
        return "content"


# --- PPTX ---------------------------------------------------------------------


class PPTXParser(Parser):
    """Extract text from PowerPoint by slide, preserving notes."""

    mime_types = ("application/vnd.openxmlformats-officedocument.presentationml.presentation",)

    def parse(self, entry: FileEntry, artifact_path: Path) -> ParsedDocument:
        from pptx import Presentation

        prs = Presentation(str(artifact_path))
        chunks: list[Chunk] = []

        for slide_num, slide in enumerate(prs.slides, start=1):
            for shape in slide.shapes:
                if not hasattr(shape, "text_frame"):
                    continue
                for para in shape.text_frame.paragraphs:
                    text = para.text.strip()
                    if not text:
                        continue
                    chunks.append(
                        Chunk(
                            text=text,
                            anchor_type="slide",
                            anchor_value=str(slide_num),
                            chunk_class=self._classify_shape(para),
                        )
                    )

        return ParsedDocument(
            file_entry=entry,
            chunks=chunks,
            metadata={
                "slide_count": len(prs.slides),
            },
            extraction_confidence=0.90,
        )

    @staticmethod
    def _classify_shape(para: Paragraph) -> str:
        # Exercise question heuristics: "?" in text, keyword "exercise", "question".
        text = para.text.lower()
        if "?" in text or "exercise" in text or "question" in text:
            return "exercise_question"
        return "content"


# --- DOCX ---------------------------------------------------------------------


class DOCXParser(Parser):
    """Extract text from Word by paragraph, with heading detection."""

    mime_types = ("application/vnd.openxmlformats-officedocument.wordprocessingml.document",)

    def parse(self, entry: FileEntry, artifact_path: Path) -> ParsedDocument:
        from docx import Document

        doc = Document(str(artifact_path))
        chunks: list[Chunk] = []

        for para_idx, para in enumerate(doc.paragraphs, start=1):
            text = para.text.strip()
            if not text:
                continue
            style = para.style.name.lower() if para.style else ""
            is_heading = "heading" in style or "title" in style
            chunks.append(
                Chunk(
                    text=text,
                    anchor_type="heading" if is_heading else "line_range",
                    anchor_value=str(para_idx),
                    chunk_class="content",
                )
            )

        return ParsedDocument(
            file_entry=entry,
            chunks=chunks,
            metadata={
                "paragraph_count": len(doc.paragraphs),
            },
            extraction_confidence=0.92,
        )


# --- Markdown ------------------------------------------------------------------


class MarkdownParser(Parser):
    """Extract text from Markdown, splitting on headings."""

    mime_types = ("text/markdown",)

    HEADING_RE = re.compile(r"^(#{1,6})\s+(.+)$")

    def parse(self, entry: FileEntry, artifact_path: Path) -> ParsedDocument:
        raw = artifact_path.read_text(encoding="utf-8")
        lines = raw.splitlines()
        chunks: list[Chunk] = []
        current_heading: str | None = None

        for line_num, line in enumerate(lines, start=1):
            m = self.HEADING_RE.match(line)
            if m:
                current_heading = m.group(2).strip()
                chunks.append(
                    Chunk(
                        text=current_heading,
                        anchor_type="heading",
                        anchor_value=str(line_num),
                        chunk_class="content",
                    )
                )
            elif line.strip():
                chunks.append(
                    Chunk(
                        text=line.strip(),
                        anchor_type="line_range",
                        anchor_value=str(line_num),
                        chunk_class="content",
                    )
                )

        return ParsedDocument(
            file_entry=entry,
            chunks=chunks,
            metadata={"line_count": len(lines)},
            extraction_confidence=0.98,
        )


# --- Plain text ----------------------------------------------------------------


class TextParser(Parser):
    """Extract plain text by line."""

    mime_types = ("text/plain",)

    def parse(self, entry: FileEntry, artifact_path: Path) -> ParsedDocument:
        raw = artifact_path.read_text(encoding="utf-8", errors="replace")
        lines = raw.splitlines()
        chunks = [
            Chunk(
                text=line,
                anchor_type="line_range",
                anchor_value=str(idx + 1),
                chunk_class="content",
            )
            for idx, line in enumerate(lines)
            if line.strip()
        ]
        return ParsedDocument(
            file_entry=entry,
            chunks=chunks,
            metadata={"line_count": len(lines)},
            extraction_confidence=0.99,
        )


# --- Registry ------------------------------------------------------------------


PARSER_REGISTRY: dict[str, Parser] = {
    mime: parser_instance
    for parser_cls in (PDFParser, PPTXParser, DOCXParser, MarkdownParser, TextParser)
    for mime in parser_cls.mime_types
    for parser_instance in [parser_cls()]
}


def parse(entry: FileEntry, artifact_path: Path) -> ParsedDocument:
    """Route *entry* to the correct parser for its MIME type."""
    parser = PARSER_REGISTRY.get(entry.mime_type)
    if parser is None:
        return ParsedDocument(
            file_entry=entry,
            chunks=[],
            extraction_status="quarantined",
            failure_reason=f"no parser for MIME type: {entry.mime_type}",
        )
    return parser(entry, artifact_path)
