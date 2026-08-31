"""Periodic file scanner.

Scans the source root, computes per-file SHA-256 checksums and emits one
``FileEntry`` per supported file. Re-scanning a file whose checksum has not changed
is a no-op at the idempotency layer.

Supported extensions: PDF, PPTX, DOCX, MD, TXT (configurable).
"""

from __future__ import annotations

import hashlib
import os
from dataclasses import dataclass
from pathlib import Path

import structlog

logger = structlog.get_logger(__name__)

# MIME → (extensions, label)
SUPPORTED_TYPES = {
    "application/pdf": (".pdf",),
    "application/vnd.openxmlformats-officedocument.presentationml.presentation": (".pptx",),
    "application/vnd.openxmlformats-officedocument.wordprocessingml.document": (".docx",),
    "text/markdown": (".md", ".markdown"),
    "text/plain": (".txt", ".text"),
}

SUPPORTED_EXTENSIONS = {
    ext for extensions in (v for v in SUPPORTED_TYPES.values()) for ext in extensions
}


@dataclass(frozen=True, slots=True)
class FileEntry:
    """A file found during a scan, before extraction."""

    relative_path: str
    absolute_path: Path
    checksum: str
    size_bytes: int
    mime_type: str
    mtime_ns: int


class Scanner:
    """Walks a source root and yields stable file entries.

    Checksums are SHA-256 and computed in 64 KiB chunks so large files do not
    dominate memory. Modification times are compared at nanosecond precision so an
    rsync-touched file is detected as a change even if the content checksum is
    identical (the idempotency key includes checksum, so a content-identical
    re-touch still produces zero new work).
    """

    def __init__(
        self,
        root: Path,
        *,
        skip_hidden: bool = True,
        skip_patterns: tuple[str, ...] = ("__MACOSX", ".DS_Store", "Thumbs.db"),
    ) -> None:
        self._root = root
        self._skip_hidden = skip_hidden
        self._skip_patterns = skip_patterns

    def scan(self) -> list[FileEntry]:
        """Walk the root and return all supported file entries."""
        entries: list[FileEntry] = []
        for dirpath, dirnames, filenames in os.walk(self._root):
            dirpath_path = Path(dirpath)

            # Prune hidden directories and known unwanted patterns in-place.
            dirnames[:] = [
                d
                for d in dirnames
                if not ((self._skip_hidden and d.startswith(".")) or d in self._skip_patterns)
            ]

            for filename in filenames:
                if filename.startswith(".") or filename in self._skip_patterns:
                    continue

                file_path = dirpath_path / filename

                try:
                    mime = self._sniff_mime(file_path)
                except PermissionError:
                    logger.warning("scanner_permission_denied", path=str(file_path))
                    continue

                if mime not in SUPPORTED_TYPES:
                    continue

                try:
                    stat_result = file_path.stat()
                except OSError as exc:
                    logger.warning("scanner_stat_failed", path=str(file_path), exc=str(exc))
                    continue

                checksum = self._sha256(file_path)
                rel = file_path.relative_to(self._root).as_posix()

                entries.append(
                    FileEntry(
                        relative_path=rel,
                        absolute_path=file_path,
                        checksum=checksum,
                        size_bytes=stat_result.st_size,
                        mime_type=mime,
                        mtime_ns=stat_result.st_mtime_ns,
                    )
                )

        logger.info("scanner_complete", root=str(self._root), files_found=len(entries))
        return entries

    def _sha256(self, path: Path) -> str:
        hasher = hashlib.sha256()
        with open(path, "rb") as f:
            for chunk in iter(lambda: f.read(65536), b""):
                hasher.update(chunk)
        return hasher.hexdigest()

    def _sniff_mime(self, path: Path) -> str:
        # Heuristic by extension first (os.walk already stat'd it); binary scan fallback.
        ext = path.suffix.lower()
        for mime, extensions in SUPPORTED_TYPES.items():
            if ext in extensions:
                return mime
        # Fallback: binary scan for PDF vs text.
        with open(path, "rb") as f:
            start = f.read(8)
        if start.startswith(b"%PDF"):
            return "application/pdf"
        # Treat printable ASCII as text.
        try:
            path.read_text(encoding="utf-8", errors="strict")
            return "text/plain"
        except (UnicodeDecodeError, ValueError):
            return "application/octet-stream"
