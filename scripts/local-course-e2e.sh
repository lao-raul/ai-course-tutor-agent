#!/usr/bin/env bash
set -euo pipefail
exec uv run python -m scripts.local_course_e2e "$@"
