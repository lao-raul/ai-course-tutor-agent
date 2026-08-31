"""Tests for source-root validation."""

from __future__ import annotations

import os
import tempfile
from pathlib import Path

import pytest
from course_tutor_ingestion.source_root import (
    SourceRootError,
    validate_path,
    validate_read_access,
)


class TestValidatePath:
    def test_rejects_relative_path(self) -> None:
        with pytest.raises(SourceRootError, match="must be absolute"):
            validate_path("data/modules")

    def test_rejects_nonexistent(self) -> None:
        with pytest.raises(SourceRootError, match="does not exist"):
            validate_path("/this/does/not/exist/at/all")

    def test_rejects_non_directory(self, tmp_path: Path) -> None:
        file = tmp_path / "afile.txt"
        file.write_text("hello")
        with pytest.raises(SourceRootError, match="not a directory"):
            validate_path(file)

    def test_accepts_valid_root(self, tmp_path: Path) -> None:
        result = validate_path(tmp_path)
        assert result == tmp_path.resolve()

    def test_rejects_symlink_pointing_outside_root(self, tmp_path: Path) -> None:
        """A symlink whose target is outside the root directory is rejected.

        The check is: resolved_path.relative_to(declared_path). If the target resolves
        to a path that is not a descendant of the symlink's parent directory,
        relative_to raises — correctly flagging an escape.
        """
        # Create a file outside tmp_path.
        outside = Path(tempfile.mkdtemp()) / "secret.txt"
        outside.write_text("outside content")
        try:
            link = tmp_path / "link_to_outside.txt"
            link.symlink_to(outside)
            with pytest.raises(SourceRootError, match="escapes declared root"):
                validate_path(link)
        finally:
            outside.unlink(missing_ok=True)
            Path(tempfile.mkdtemp()).rmdir()

    def test_rejects_deep_symlink_pointing_outside(self, tmp_path: Path) -> None:
        """A symlink two levels deep whose target is outside the root is rejected."""
        outside = Path(tempfile.mkdtemp()) / "secret.txt"
        outside.write_text("outside content")
        try:
            deep_dir = tmp_path / "a" / "b"
            deep_dir.mkdir(parents=True)
            link = deep_dir / "link.txt"
            link.symlink_to(outside)
            with pytest.raises(SourceRootError, match="escapes declared root"):
                validate_path(link)
        finally:
            outside.unlink(missing_ok=True)
            Path(tempfile.mkdtemp()).rmdir()


class TestValidateReadAccess:
    def test_rejects_unreadable_directory(self, tmp_path: Path) -> None:
        # Make the directory unreadable.
        os.chmod(tmp_path, 0o000)
        try:
            with pytest.raises(SourceRootError, match="lacks read/execute"):
                validate_read_access(tmp_path)
        finally:
            os.chmod(tmp_path, 0o755)  # noqa: S103  # reset after test

    def test_accepts_readable_directory(self, tmp_path: Path) -> None:
        validate_read_access(tmp_path)  # Should not raise.
