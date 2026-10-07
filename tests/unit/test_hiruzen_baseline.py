"""Machine-check the accepted Hiruzen v0.3 baseline."""

from __future__ import annotations

import subprocess
import sys
from pathlib import Path


def test_hiruzen_baseline_is_consistent() -> None:
    root = Path(__file__).resolve().parents[2]
    result = subprocess.run(
        [sys.executable, "scripts/validate_hiruzen_baseline.py"],
        cwd=root,
        check=False,
        capture_output=True,
        text=True,
    )
    assert result.returncode == 0, result.stdout + result.stderr
    assert "Hiruzen baseline valid" in result.stdout
