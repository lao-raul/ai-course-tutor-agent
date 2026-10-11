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
  deployment/course-tutor-practice-api \
  deployment/course-tutor-practice-worker \
  deployment/course-tutor-worker \
  deployment/course-tutor-web \
  deployment/course-tutor-fake-llm \
  -n "${namespace}"

kubectl rollout status deployment/course-tutor-backend -n "${namespace}" --timeout=5m
kubectl rollout status deployment/course-tutor-practice-api -n "${namespace}" --timeout=5m
kubectl rollout status deployment/course-tutor-practice-worker -n "${namespace}" --timeout=5m
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
test "${containers}" = "agent-api"
practice_pod="$(kubectl get pods -n "${namespace}" -l app.kubernetes.io/component=practice-api -o jsonpath='{.items[0].metadata.name}')"
worker_pod="$(kubectl get pods -n "${namespace}" -l app.kubernetes.io/component=practice-worker -o jsonpath='{.items[0].metadata.name}')"
test -n "${practice_pod}" && test -n "${worker_pod}"
test "$(kubectl get pod "${practice_pod}" -n "${namespace}" -o jsonpath='{.spec.containers[0].name}')" = practice-api
test "$(kubectl get pod "${worker_pod}" -n "${namespace}" -o jsonpath='{.spec.containers[0].name}')" = practice-worker
for pod in "${practice_pod}" "${worker_pod}"; do
  if kubectl get pod "${pod}" -n "${namespace}" -o json | jq -e '.spec.volumes[]? | select(.name == "course-content")' >/dev/null; then
    echo "Practice pod ${pod} mounted course content" >&2
    exit 1
  fi
done

helm test "${release}" --namespace "${namespace}" --logs --timeout 2m

echo "Verified independent Agent, Practice API and Practice Worker workloads."
