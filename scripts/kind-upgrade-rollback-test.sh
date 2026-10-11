#!/usr/bin/env bash
set -euo pipefail

# This drill must never target the real-course cluster or a production release.
cluster_name="${1:-course-tutor-ci}"
if [[ "${cluster_name}" != course-tutor-ci* ]]; then
  echo "Upgrade/rollback drill is restricted to a disposable course-tutor-ci Kind cluster" >&2
  exit 1
fi

repo_root="$(cd "$(dirname "${BASH_SOURCE[0]}")/.." && pwd)"
namespace="course-tutor"
release="course-tutor"
chart="${repo_root}/infra/k8s/course-tutor"

kind get clusters | grep -Fxq "${cluster_name}"
kind export kubeconfig --name "${cluster_name}" >/dev/null
test "$(kubectl config current-context)" = "kind-${cluster_name}"

values="$(helm get values "${release}" -n "${namespace}" -o json)"
jq -e '.config.environment == "test" and .courseContent.enabled == false' \
  <<<"${values}" >/dev/null

initial_revision="$(helm status "${release}" -n "${namespace}" -o json | jq -r '.version')"
test "${initial_revision}" -ge 1
build_revision="$(jq -r '.global.buildRevision // "unknown"' <<<"${values}")"

helm upgrade "${release}" "${chart}" -n "${namespace}" \
  --reuse-values \
  --set-string "global.buildRevision=${build_revision}-upgrade-drill" \
  --wait --wait-for-jobs --timeout 10m
helm test "${release}" -n "${namespace}" --logs --timeout 5m

upgraded_revision="$(helm status "${release}" -n "${namespace}" -o json | jq -r '.version')"
test "${upgraded_revision}" -gt "${initial_revision}"

helm rollback "${release}" "${initial_revision}" -n "${namespace}" \
  --wait --wait-for-jobs --timeout 10m
helm test "${release}" -n "${namespace}" --logs --timeout 5m

rolled_back_revision="$(helm status "${release}" -n "${namespace}" -o json | jq -r '.version')"
test "${rolled_back_revision}" -gt "${upgraded_revision}"
test "$(helm get values "${release}" -n "${namespace}" -o json \
  | jq -r '.global.buildRevision')" = "${build_revision}"

for deployment in course-tutor-backend course-tutor-practice-api \
  course-tutor-practice-worker course-tutor-web; do
  kubectl rollout status "deployment/${deployment}" -n "${namespace}" --timeout=5m
done

echo "Verified isolated Kind Helm upgrade ${initial_revision}->${upgraded_revision}, rollback ${rolled_back_revision}, and smoke tests."
