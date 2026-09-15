#!/usr/bin/env bash
set -euo pipefail

repo_root="$(cd "$(dirname "${BASH_SOURCE[0]}")/.." && pwd)"
output="${RELEASE_READINESS_OUTPUT:-${repo_root}/build/reports/release-readiness.json}"
mkdir -p "$(dirname "${output}")"

cd "${repo_root}"
uv run python scripts/validate_delivery.py
uv run pytest tests/unit tests/integration/ingestion/test_version_lifecycle.py \
  tests/integration/memory/test_memory_lifecycle.py -q
helm lint infra/k8s/course-tutor -f infra/k8s/course-tutor/values-ci.yaml
helm template course-tutor infra/k8s/course-tutor \
  -f infra/k8s/course-tutor/values-ci.yaml >/dev/null
npm --prefix apps/web test -- --run
npm --prefix apps/web run build

cluster_drills="not-requested"
if [[ "${RUN_CLUSTER_DRILLS:-false}" == "true" ]]; then
  scripts/ha-drill.sh
  CONFIRM_NON_PRODUCTION=yes scripts/restore-drill.sh
  CONFIRM_NON_PRODUCTION=yes scripts/helm-rollback-drill.sh
  cluster_drills="passed"
fi

jq -n --arg commit "$(git rev-parse HEAD)" \
  --arg verified_at "$(date -u +%Y-%m-%dT%H:%M:%SZ)" \
  --arg cluster_drills "${cluster_drills}" \
  '{commit: $commit, verified_at: $verified_at, static_delivery: "passed",
    unit_and_idempotency: "passed", helm: "passed", frontend: "passed",
    cluster_drills: $cluster_drills}' > "${output}"
cat "${output}"
