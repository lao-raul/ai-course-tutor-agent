#!/usr/bin/env bash
set -euo pipefail

cluster_name="${1:-course-tutor-local}"
repo_root="$(cd "$(dirname "${BASH_SOURCE[0]}")/.." && pwd)"
namespace="course-tutor"
deployment="course-tutor-negative-readiness"

invalid_report="${repo_root}/build/reports/invalid-helm-values.txt"
mkdir -p "$(dirname "${invalid_report}")"
if helm lint "${repo_root}/infra/k8s/course-tutor" \
  --values "${repo_root}/infra/k8s/course-tutor/values-ci.yaml" \
  --set backend.replicas=0 >"${invalid_report}" 2>&1; then
  echo "Invalid Helm values unexpectedly passed schema validation" >&2
  exit 1
fi

kind export kubeconfig --name "${cluster_name}" >/dev/null

cleanup() {
  kubectl delete deployment "${deployment}" -n "${namespace}" \
    --ignore-not-found --wait >/dev/null
}
trap cleanup EXIT

kubectl apply -f "${repo_root}/infra/k8s/course-tutor/tests/negative-readiness.yaml"

if kubectl rollout status deployment/"${deployment}" -n "${namespace}" --timeout=30s; then
  echo "Broken readiness probe unexpectedly completed its rollout" >&2
  exit 1
fi

echo "Verified invalid Helm values and a broken readiness probe both fail closed."
