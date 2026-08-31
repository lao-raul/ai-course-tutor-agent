"""Ingestion service: scanning, parsing, chunking and indexing."""

# Re-export surface-only (no internal dependencies) to avoid breaking
# `from course_tutor_ingestion import SourceRootError` used by admin.py.
from course_tutor_ingestion.source_root import (
    SourceRootError,
    validate_path,
    validate_read_access,
)

__all__ = [
    "Chunk",
    "FileEntry",
    "ParsedDocument",
    "Scanner",
    "SourceRootError",
    "parse",
    "validate_path",
    "validate_read_access",
]
