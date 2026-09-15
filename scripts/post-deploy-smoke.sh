#!/usr/bin/env bash
set -euo pipefail

namespace="${NAMESPACE:-course-tutor}"
service_prefix="${SERVICE_PREFIX:-course-tutor}"
agent_port="${AGENT_FORWARD_PORT:-28000}"
practice_port="${PRACTICE_FORWARD_PORT:-28001}"
web_port="${WEB_FORWARD_PORT:-28080}"
token="${SMOKE_BEARER_TOKEN:?SMOKE_BEARER_TOKEN is required}"
course_id="${SMOKE_COURSE_ID:-}"
query="${SMOKE_QUERY:-Summarize the first unit.}"
require_rag="${SMOKE_RAG_REQUIRED:-true}"
tmp_dir="$(mktemp -d)"

cleanup() {
  for pid in $(jobs -pr); do
    kill "${pid}" >/dev/null 2>&1 || true
  done
  rm -rf "${tmp_dir}"
}
trap cleanup EXIT

kubectl -n "${namespace}" port-forward "service/${service_prefix}-agent" "${agent_port}:8000" \
  >"${tmp_dir}/agent-forward.log" 2>&1 &
kubectl -n "${namespace}" port-forward "service/${service_prefix}-practice" "${practice_port}:8001" \
  >"${tmp_dir}/practice-forward.log" 2>&1 &
kubectl -n "${namespace}" port-forward "service/${service_prefix}-web" "${web_port}:80" \
  >"${tmp_dir}/web-forward.log" 2>&1 &

wait_for_url() {
  local url="$1"
  for _ in $(seq 1 60); do
    if curl --fail --silent --show-error "${url}" >/dev/null 2>&1; then
      return
    fi
    sleep 1
  done
  echo "Timed out waiting for ${url}" >&2
  return 1
}

wait_for_url "http://127.0.0.1:${agent_port}/healthz"
wait_for_url "http://127.0.0.1:${practice_port}/healthz"
wait_for_url "http://127.0.0.1:${web_port}/"

curl --fail --silent --show-error "http://127.0.0.1:${agent_port}/readyz" | jq -e '.status == "ready"' >/dev/null
curl --fail --silent --show-error "http://127.0.0.1:${practice_port}/readyz" | jq -e '.status == "ready"' >/dev/null
curl --fail --silent --show-error \
  --header "Authorization: Bearer ${token}" \
  "http://127.0.0.1:${practice_port}/v1/practice/capabilities" \
  | jq -e '.exercise_generation == "not_implemented"' >/dev/null
curl --fail --silent --show-error "http://127.0.0.1:${agent_port}/metrics" \
  | grep -q '^course_tutor_http_requests_total'
curl --fail --silent --show-error "http://127.0.0.1:${practice_port}/metrics" \
  | grep -q '^course_tutor_http_requests_total'

if [[ -n "${course_id}" ]]; then
  curl --fail --silent --show-error --no-buffer \
    --header "Authorization: Bearer ${token}" \
    --header "Content-Type: application/json" \
    --data "$(jq -cn --arg query "${query}" '{query: $query}')" \
    "http://127.0.0.1:${agent_port}/v1/courses/${course_id}/chat" \
    > "${tmp_dir}/rag.sse"
  grep -q '^event: done' "${tmp_dir}/rag.sse"
  if ! grep -Eq '^event: (citation|abstained)' "${tmp_dir}/rag.sse"; then
    echo "RAG smoke returned neither a citation nor an explicit abstention" >&2
    exit 1
  fi
elif [[ "${require_rag}" == "true" ]]; then
  echo "SMOKE_COURSE_ID is required when SMOKE_RAG_REQUIRED=true" >&2
  exit 1
fi

echo "Post-deploy Agent, Practice, Web, metrics and RAG smoke checks passed."
