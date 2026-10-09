"""Compare a local FLTRP pilot PDF with the redacted TASK-24 manifest."""

from __future__ import annotations

import argparse
import hashlib
import json
from pathlib import Path
from typing import Any

from course_tutor_ingestion.outline import EXTRACTOR_VERSION, extract_pdf_outline

ROOT = Path(__file__).resolve().parents[1]
MANIFEST = ROOT / "tests/fixtures/hiruzen/outlines/fltrp-chen-lin-grade-3-first-term.json"


def _checksum(path: Path) -> str:
    digest = hashlib.sha256()
    with path.open("rb") as stream:
        while block := stream.read(1024 * 1024):
            digest.update(block)
    return digest.hexdigest()


def _safe_nodes(outline: Any) -> list[dict[str, object]]:
    return [
        {"title": node.title, "page_start": node.page_start, "depth": node.depth}
        for node in outline.nodes
    ]


def verify(pdf_path: Path) -> None:
    manifest = json.loads(MANIFEST.read_text(encoding="utf-8"))
    outline = extract_pdf_outline(pdf_path, _checksum(pdf_path))
    actual = {
        "extractor_version": EXTRACTOR_VERSION,
        "availability": outline.availability,
        "provenance": outline.provenance,
        "confidence": outline.confidence,
        "nodes": _safe_nodes(outline),
    }
    expected = {key: manifest[key] for key in actual}
    if actual != expected:
        raise SystemExit(
            "FAIL pilot outline differs from the redacted manifest; "
            f"actual availability={outline.availability}, provenance={outline.provenance}, "
            f"confidence={outline.confidence}, nodes={len(outline.nodes)}"
        )
    print(
        "PASS FLTRP pilot outline "
        f"extractor={EXTRACTOR_VERSION} provenance={outline.provenance} "
        f"confidence={outline.confidence} nodes={len(outline.nodes)}"
    )


def main() -> None:
    parser = argparse.ArgumentParser()
    parser.add_argument("--pdf", type=Path, required=True)
    args = parser.parse_args()
    verify(args.pdf)


if __name__ == "__main__":
    main()
