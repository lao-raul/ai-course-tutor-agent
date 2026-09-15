#!/usr/bin/env bash
set -euo pipefail

test "${CONFIRM_NON_PRODUCTION:-}" = "yes" || {
  echo "Set CONFIRM_NON_PRODUCTION=yes after selecting a disposable namespace" >&2
  exit 1
}

repo_root="$(cd "$(dirname "${BASH_SOURCE[0]}")/.." && pwd)"
namespace="${NAMESPACE:-course-tutor}"
release="${HELM_RELEASE:-course-tutor}"
output="${ROLLBACK_DRILL_OUTPUT:-${repo_root}/build/reports/rollback-drill.json}"
before_revision="$(helm history "${release}" -n "${namespace}" -o json | jq -r '.[-1].revision')"
before_image="$(kubectl -n "${namespace}" get deployment course-tutor-backend \
  -o jsonpath='{.spec.template.spec.containers[?(@.name=="agent-api")].image}')"

if helm upgrade "${release}" "${repo_root}/infra/k8s/course-tutor" \
  --namespace "${namespace}" --reuse-values \
  --set-string config.llmBaseUrl=http://127.0.0.1:1/v1 \
  --set-string global.verificationResult=expected-failure \
  --atomic --wait --timeout "${ROLLBACK_FAILURE_TIMEOUT:-75s}"; then
  echo "Expected readiness failure unexpectedly succeeded" >&2
  exit 1
fi

helm status "${release}" -n "${namespace}" -o json | jq -e '.info.status == "deployed"' >/dev/null
kubectl -n "${namespace}" rollout status deployment/course-tutor-backend --timeout=5m
after_image="$(kubectl -n "${namespace}" get deployment course-tutor-backend \
  -o jsonpath='{.spec.template.spec.containers[?(@.name=="agent-api")].image}')"
test "${after_image}" = "${before_image}"

helm upgrade "${release}" "${repo_root}/infra/k8s/course-tutor" \
  --namespace "${namespace}" --reuse-values \
  --set-string global.verificationResult=rollback-drill \
  --atomic --wait --timeout 5m
temporary_revision="$(helm history "${release}" -n "${namespace}" -o json | jq -r '.[-1].revision')"
helm rollback "${release}" "${before_revision}" -n "${namespace}" --wait --timeout 5m
kubectl -n "${namespace}" rollout status deployment/course-tutor-backend --timeout=5m

mkdir -p "$(dirname "${output}")"
jq -n --arg before_revision "${before_revision}" \
  --arg temporary_revision "${temporary_revision}" \
  --arg final_revision "$(helm history "${release}" -n "${namespace}" -o json | jq -r '.[-1].revision')" \
  --arg image "${before_image}" \
  '{failed_rollout_auto_rollback: "passed", manual_rollback: "passed",
    original_revision: $before_revision, temporary_revision: $temporary_revision,
    final_revision: $final_revision, preserved_image: $image}' > "${output}"
cat "${output}"
