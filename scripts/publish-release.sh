#!/usr/bin/env bash
set -euo pipefail

repo_root="$(cd "$(dirname "${BASH_SOURCE[0]}")/.." && pwd)"
registry_prefix="${REGISTRY_PREFIX:?REGISTRY_PREFIX is required, for example ghcr.io/owner/repository}"
registry_prefix="${registry_prefix,,}"
release_sha="${RELEASE_SHA:-$(git -C "${repo_root}" rev-parse HEAD)}"
output_dir="${RELEASE_OUTPUT_DIR:-${repo_root}/build/release}"
platforms="${RELEASE_PLATFORMS:-linux/amd64,linux/arm64}"
source_url="${BUILD_SOURCE:-https://github.com/example/ai-course-tutor-agent}"

test "$(git -C "${repo_root}" rev-parse HEAD)" = "${release_sha}" || {
  echo "Checked-out commit does not equal RELEASE_SHA" >&2
  exit 1
}

mkdir -p "${output_dir}/metadata" "${output_dir}/charts"
short_sha="${release_sha:0:12}"
base_version="$(sed -n 's/^appVersion: "\([^"]*\)"/\1/p' "${repo_root}/infra/k8s/course-tutor/Chart.yaml")"
release_version="${base_version}-${short_sha}"

build_image() {
  local key="$1"
  local image_name="$2"
  local dockerfile="$3"
  local image="${registry_prefix}/${image_name}"
  local metadata="${output_dir}/metadata/${key}.json"

  docker buildx build "${repo_root}" \
    --file "${repo_root}/${dockerfile}" \
    --platform "${platforms}" \
    --tag "${image}:sha-${release_sha}" \
    --label "org.opencontainers.image.version=${release_version}" \
    --label "org.opencontainers.image.revision=${release_sha}" \
    --label "org.opencontainers.image.source=${source_url}" \
    --provenance=mode=max \
    --sbom=true \
    --metadata-file "${metadata}" \
    --push >&2

  local digest
  digest="$(jq -er '."containerimage.digest"' "${metadata}")"
  if command -v cosign >/dev/null 2>&1; then
    cosign sign --yes "${image}@${digest}" >&2
  elif [[ "${REQUIRE_COSIGN:-false}" == "true" ]]; then
    echo "cosign is required for release publication" >&2
    return 1
  fi
  printf '%s' "${digest}"
}

agent_digest="$(build_image agent course-tutor-agent apps/api/Dockerfile)"
practice_digest="$(build_image practice course-tutor-practice apps/practice/Dockerfile)"
worker_digest="$(build_image worker course-tutor-worker services/ingestion/Dockerfile)"
web_digest="$(build_image web course-tutor-web apps/web/Dockerfile)"

helm package "${repo_root}/infra/k8s/course-tutor" \
  --version "${release_version}" \
  --app-version "${release_version}" \
  --destination "${output_dir}/charts"
chart_archive="${output_dir}/charts/course-tutor-${release_version}.tgz"
helm push "${chart_archive}" "oci://${registry_prefix}/charts"

jq -n \
  --arg schema_version "1" \
  --arg release_sha "${release_sha}" \
  --arg release_version "${release_version}" \
  --arg chart "oci://${registry_prefix}/charts/course-tutor:${release_version}" \
  --arg actor "${GITHUB_ACTOR:-local}" \
  --arg created_at "$(date -u +%Y-%m-%dT%H:%M:%SZ)" \
  --arg agent_repository "${registry_prefix}/course-tutor-agent" \
  --arg agent_digest "${agent_digest}" \
  --arg practice_repository "${registry_prefix}/course-tutor-practice" \
  --arg practice_digest "${practice_digest}" \
  --arg worker_repository "${registry_prefix}/course-tutor-worker" \
  --arg worker_digest "${worker_digest}" \
  --arg web_repository "${registry_prefix}/course-tutor-web" \
  --arg web_digest "${web_digest}" \
  '{
    schema_version: $schema_version,
    release_sha: $release_sha,
    release_version: $release_version,
    chart: $chart,
    actor: $actor,
    created_at: $created_at,
    images: {
      agent: {repository: $agent_repository, digest: $agent_digest},
      practice: {repository: $practice_repository, digest: $practice_digest},
      worker: {repository: $worker_repository, digest: $worker_digest},
      web: {repository: $web_repository, digest: $web_digest}
    }
  }' > "${output_dir}/release-manifest.json"

if [[ -n "${GITHUB_OUTPUT:-}" ]]; then
  {
    echo "release_sha=${release_sha}"
    echo "release_version=${release_version}"
    echo "agent_digest=${agent_digest}"
    echo "practice_digest=${practice_digest}"
    echo "worker_digest=${worker_digest}"
    echo "web_digest=${web_digest}"
  } >> "${GITHUB_OUTPUT}"
fi

jq . "${output_dir}/release-manifest.json"
