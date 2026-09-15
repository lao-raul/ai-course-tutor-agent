#!/usr/bin/env bash
set -euo pipefail

manifest="${1:?usage: verify-release-digests.sh RELEASE_MANIFEST [NAMESPACE]}"
namespace="${2:-course-tutor}"
service_prefix="${SERVICE_PREFIX:-course-tutor}"

expected_digest() { jq -er ".images.$1.digest" "${manifest}"; }

verify_container() {
  local component="$1"
  local container="$2"
  local image_key="$3"
  local expected
  expected="$(expected_digest "${image_key}")"
  local image_ids
  image_ids="$(kubectl -n "${namespace}" get pods \
    -l "app.kubernetes.io/component=${component}" \
    -o json | jq -r --arg container "${container}" \
    '.items[].status.containerStatuses[] | select(.name == $container) | .imageID')"
  test -n "${image_ids}"
  while IFS= read -r image_id; do
    [[ "${image_id}" == *@"${expected}" ]] || {
      echo "${container} is running ${image_id}, expected ${expected}" >&2
      return 1
    }
  done <<< "${image_ids}"
}

verify_container backend agent-api agent
verify_container backend practice-api practice
verify_container worker ingestion-worker worker
verify_container web web web

kubectl -n "${namespace}" get configmap "${service_prefix}-release-metadata" -o json \
  | jq -e --arg revision "$(jq -r .release_sha "${manifest}")" \
    '.data.revision == $revision' >/dev/null

echo "All running workload image IDs match the published release manifest."
