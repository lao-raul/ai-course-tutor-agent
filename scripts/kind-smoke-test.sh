#!/usr/bin/env bash
set -euo pipefail

cluster_name="${1:-course-tutor-local}"
repo_root="$(cd "$(dirname "${BASH_SOURCE[0]}")/.." && pwd)"
namespace="course-tutor"
release="course-tutor"

kind get clusters | grep -Fxq "${cluster_name}" || {
  echo "Kind cluster ${cluster_name} does not exist" >&2
  exit 1
}

helm upgrade --install "${release}" "${repo_root}/infra/k8s/course-tutor" \
  --namespace "${namespace}" \
  --create-namespace \
  --values "${repo_root}/infra/k8s/course-tutor/values-ci.yaml" \
  --set-string global.buildRevision="$(git -C "${repo_root}" rev-parse --short HEAD)" \
  --atomic \
  --wait \
  --wait-for-jobs \
  --timeout 10m

# Local development and CI both reuse immutable-looking local tags. Restart the
# application workloads so a newly loaded image cannot be masked by a stale Pod.
kubectl rollout restart \
  deployment/course-tutor-backend \
  deployment/course-tutor-worker \
  deployment/course-tutor-web \
  deployment/course-tutor-fake-llm \
  -n "${namespace}"

kubectl rollout status deployment/course-tutor-backend -n "${namespace}" --timeout=5m
kubectl rollout status deployment/course-tutor-worker -n "${namespace}" --timeout=5m
kubectl rollout status deployment/course-tutor-web -n "${namespace}" --timeout=5m
kubectl rollout status deployment/course-tutor-fake-llm -n "${namespace}" --timeout=5m

backend_pod="$(
  kubectl get pods -n "${namespace}" \
    -l app.kubernetes.io/component=backend \
    -o jsonpath='{.items[0].metadata.name}'
)"
containers="$(
  kubectl get pod "${backend_pod}" -n "${namespace}" \
    -o jsonpath='{range .spec.containers[*]}{.name}{"\n"}{end}' | sort | paste -sd, -
)"
test "${containers}" = "agent-api,practice-api"

helm test "${release}" --namespace "${namespace}" --logs --timeout 2m

echo "Verified ${backend_pod}: agent-api and practice-api are Ready in one Pod."
