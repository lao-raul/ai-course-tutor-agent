#!/usr/bin/env bash
set -euo pipefail

repo_root="$(cd "$(dirname "${BASH_SOURCE[0]}")/.." && pwd)"
cd "${repo_root}"

export TAG="${TAG:-dev}"
export BUILD_VERSION="${BUILD_VERSION:-0.1.0-dev}"
export BUILD_REVISION="${BUILD_REVISION:-$(git rev-parse --short=12 HEAD 2>/dev/null || echo unknown)}"
export BUILD_SOURCE="${BUILD_SOURCE:-https://github.com/example/ai-course-tutor-agent}"
export BUILDX_NO_DEFAULT_ATTESTATIONS="${BUILDX_NO_DEFAULT_ATTESTATIONS:-1}"

docker buildx bake "$@"
