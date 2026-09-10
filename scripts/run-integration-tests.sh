#!/usr/bin/env bash
set -euo pipefail

repo_root="$(cd "$(dirname "${BASH_SOURCE[0]}")/.." && pwd)"
compose_file="${repo_root}/infra/docker/docker-compose.test.yml"

cleanup() {
  docker compose -f "${compose_file}" down --volumes --remove-orphans
}
trap cleanup EXIT

docker compose -f "${compose_file}" up --detach --wait

export TEST_POSTGRES_DSN="postgresql+asyncpg://course_tutor:course_tutor@127.0.0.1:55432/course_tutor_test_local"
export TEST_REDIS_URL="redis://127.0.0.1:56379/0"
export TEST_QDRANT_URL="http://127.0.0.1:56333"
export TEST_MINIO_ENDPOINT="http://127.0.0.1:59000"

cd "${repo_root}"
mkdir -p build/reports
uv run --frozen pytest tests/integration tests/e2e \
  --junitxml=build/reports/integration.xml "$@"
uv run --frozen python tests/retrieval_benchmark.py \
  --output build/reports/rag-metrics.json
