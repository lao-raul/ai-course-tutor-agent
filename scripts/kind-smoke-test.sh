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

kubectl rollout status deployment/course-tutor-backend -n "${namespace}" --timeout=5m

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

kubectl wait -n "${namespace}" \
  --for=condition=Ready pod \
  -l "app.kubernetes.io/instance=${release},app.kubernetes.io/component!=migration,app.kubernetes.io/component!=helm-test" \
  --timeout=5m

helm test "${release}" --namespace "${namespace}" --logs --timeout 2m

echo "Verified ${backend_pod}: agent-api and practice-api are Ready in one Pod."
