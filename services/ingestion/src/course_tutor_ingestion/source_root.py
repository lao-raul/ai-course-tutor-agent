"""Source-root validation.

The source root is a read-only mounted POSIX directory. We validate three properties
that the app cannot trust the OS to enforce alone:

1. It must be absolute (relative paths are meaningless without a cwd guarantee).
2. It must exist.
3. It must be a real path — symlinks are resolved, so the resolved path must remain
   under the intended root (no symlink escape).

Spec §7.5 states the app only reads a local POSIX path; the host is responsible for
mounting and for not exposing SMB credentials. This module enforces what the app
*can* check locally.
"""

from __future__ import annotations

import os
from pathlib import Path

import structlog

logger = structlog.get_logger(__name__)


class SourceRootError(ValueError):
    """Raised when a source root fails local validation."""

    pass


def validate_path(raw: str | Path) -> Path:
    """Return the validated, resolved absolute path, or raise SourceRootError.

    Checks:
    - Absolute (relative paths have no guaranteed cwd in a service context).
    - Exists and is a directory.
    - Resolved path stays under the declared root (no symlink escape).
    """
    path = Path(raw)

    if not path.is_absolute():
        raise SourceRootError(f"source root must be absolute, got: {raw!r}")

    import os as _os

    # Get the real filesystem locations of the symlink and its parent directory.
    target_real = _os.path.realpath(str(path))  # Resolved target (follows symlink)
    parent_real = _os.path.realpath(str(path.parent))  # Canonical parent directory

    # The target must live inside the canonical parent directory.
    target_path = Path(target_real)
    parent_path = Path(parent_real)
    if not (target_path == parent_path or parent_path in target_path.parents):
        raise SourceRootError(
            f"resolved path {target_path} escapes declared root {path}; "
            "symlink escape is not permitted"
        )

    resolved = target_path

    if not resolved.exists():
        raise SourceRootError(f"source root does not exist: {path}")

    if not resolved.is_dir():
        raise SourceRootError(f"source root is not a directory: {path}")

    logger.debug(
        "source_root_validated",
        declared=str(path),
        resolved=str(resolved),
    )
    return resolved


def validate_read_access(path: Path) -> None:
    """Raise SourceRootError if the process cannot list and read files under *path*."""
    if not os.access(path, os.R_OK | os.X_OK):
        raise SourceRootError(f"process lacks read/execute permission on source root: {path}")
    logger.debug("source_root_read_access_ok", path=str(path))
