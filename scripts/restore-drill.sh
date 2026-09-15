#!/usr/bin/env bash
set -euo pipefail

test "${CONFIRM_NON_PRODUCTION:-}" = "yes" || {
  echo "Set CONFIRM_NON_PRODUCTION=yes after selecting a disposable namespace" >&2
  exit 1
}

namespace="${NAMESPACE:-course-tutor}"
output="${RESTORE_DRILL_OUTPUT:-build/reports/restore-drill.json}"
max_rto_seconds="${RESTORE_MAX_RTO_SECONDS:-14400}"
started="$(date +%s)"
probe="restore-probe-$(date +%s)"
backup_file="$(mktemp)"

cleanup() {
  rm -f "${backup_file}"
}
trap cleanup EXIT

environment="$(kubectl -n "${namespace}" get configmap course-tutor-release-metadata \
  -o jsonpath='{.data.environment}')"
test "${environment}" != "production"
postgres_pod="$(kubectl -n "${namespace}" get pods -l app.kubernetes.io/component=postgres \
  -o jsonpath='{.items[0].metadata.name}')"

kubectl -n "${namespace}" exec "${postgres_pod}" -c postgres -- \
  psql -U course_tutor -d course_tutor -v ON_ERROR_STOP=1 \
  -c "CREATE TABLE IF NOT EXISTS ops_restore_probe(value text PRIMARY KEY); INSERT INTO ops_restore_probe VALUES ('${probe}');"
kubectl -n "${namespace}" exec "${postgres_pod}" -c postgres -- \
  pg_dump -U course_tutor -d course_tutor -Fc -t ops_restore_probe > "${backup_file}"
kubectl -n "${namespace}" exec "${postgres_pod}" -c postgres -- \
  psql -U course_tutor -d course_tutor -v ON_ERROR_STOP=1 -c "DROP TABLE ops_restore_probe;"
kubectl -n "${namespace}" exec -i "${postgres_pod}" -c postgres -- \
  pg_restore -U course_tutor -d course_tutor --clean --if-exists < "${backup_file}"
restored="$(kubectl -n "${namespace}" exec "${postgres_pod}" -c postgres -- \
  psql -U course_tutor -d course_tutor -Atc "SELECT value FROM ops_restore_probe LIMIT 1")"
test "${restored}" = "${probe}"
kubectl -n "${namespace}" exec "${postgres_pod}" -c postgres -- \
  psql -U course_tutor -d course_tutor -c "DROP TABLE ops_restore_probe;" >/dev/null

elapsed="$(( $(date +%s) - started ))"
test "${elapsed}" -le "${max_rto_seconds}"
mkdir -p "$(dirname "${output}")"
jq -n --arg environment "${environment}" --argjson elapsed_seconds "${elapsed}" \
  --argjson rto_target_seconds "${max_rto_seconds}" --arg restored_probe "${probe}" \
  '{environment: $environment, postgres_restore: "passed", restored_probe: $restored_probe,
    elapsed_seconds: $elapsed_seconds, rto_target_seconds: $rto_target_seconds,
    rpo_target_hours: 24}' > "${output}"
cat "${output}"
