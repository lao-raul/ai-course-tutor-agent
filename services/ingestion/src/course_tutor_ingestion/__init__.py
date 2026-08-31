"""Ingestion service: scanning, parsing, chunking and indexing."""

from course_tutor_ingestion.jobs import IngestionJob, IngestionStats, run_pending_jobs
from course_tutor_ingestion.parsers import (
    Chunk,
    ParsedDocument,
    parse,
)
from course_tutor_ingestion.scanner import FileEntry, Scanner
from course_tutor_ingestion.source_root import (
    SourceRootError,
    validate_path,
    validate_read_access,
)

__all__ = [
    "Chunk",
    "FileEntry",
    "IngestionJob",
    "IngestionStats",
    "ParsedDocument",
    "Scanner",
    "SourceRootError",
    "parse",
    "run_pending_jobs",
    "validate_path",
    "validate_read_access",
]
