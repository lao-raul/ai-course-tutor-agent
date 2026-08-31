"""Allow `python -m course_tutor_ingestion` as the worker entrypoint."""

from __future__ import annotations

import asyncio
import sys

from course_tutor_ingestion.cli import main

if __name__ == "__main__":
    sys.exit(asyncio.run(main()))
