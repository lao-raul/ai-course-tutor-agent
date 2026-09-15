#!/usr/bin/env bash
set -euo pipefail

manifest="${1:?usage: deploy-release.sh RELEASE_MANIFEST CHART_ARCHIVE VALUES_FILE ENVIRONMENT}"
chart_archive="${2:?chart archive is required}"
values_file="${3:?environment values file is required}"
environment="${4:?environment is required}"
namespace="${NAMESPACE:-course-tutor}"
release="${HELM_RELEASE:-course-tutor}"
repo_root="$(cd "$(dirname "${BASH_SOURCE[0]}")/.." && pwd)"
record_dir="${DEPLOY_OUTPUT_DIR:-${repo_root}/build/release}"
mkdir -p "${record_dir}"

previous_revision="$(helm history "${release}" -n "${namespace}" -o json 2>/dev/null \
  | jq -r '[.[] | select(.status == "deployed")][-1].revision // empty')"

helm upgrade --install "${release}" "${chart_archive}" \
  --namespace "${namespace}" --create-namespace \
  --values "${values_file}" \
  --set-string "global.buildRevision=$(jq -r .release_sha "${manifest}")" \
  --set-string "global.releaseActor=${GITHUB_ACTOR:-local}" \
  --set-string "global.releaseEnvironment=${environment}" \
  --set-string "global.verificationResult=pending" \
  --set-string "backend.agent.image.repository=$(jq -r .images.agent.repository "${manifest}")" \
  --set-string "backend.agent.image.digest=$(jq -r .images.agent.digest "${manifest}")" \
  --set-string "backend.practice.image.repository=$(jq -r .images.practice.repository "${manifest}")" \
  --set-string "backend.practice.image.digest=$(jq -r .images.practice.digest "${manifest}")" \
  --set-string "worker.image.repository=$(jq -r .images.worker.repository "${manifest}")" \
  --set-string "worker.image.digest=$(jq -r .images.worker.digest "${manifest}")" \
  --set-string "web.image.repository=$(jq -r .images.web.repository "${manifest}")" \
  --set-string "web.image.digest=$(jq -r .images.web.digest "${manifest}")" \
  --atomic --wait --wait-for-jobs --timeout "${HELM_TIMEOUT:-15m}"

if ! "${repo_root}/scripts/verify-release-digests.sh" "${manifest}" "${namespace}" \
  || ! "${repo_root}/scripts/post-deploy-smoke.sh"; then
  kubectl -n "${namespace}" patch configmap course-tutor-release-metadata \
    --type merge -p '{"data":{"verification-result":"failed"}}' >/dev/null || true
  if [[ "${environment}" != "production" && -n "${previous_revision}" ]]; then
    helm rollback "${release}" "${previous_revision}" -n "${namespace}" \
      --wait --timeout "${HELM_TIMEOUT:-15m}"
  fi
  exit 1
fi

kubectl -n "${namespace}" patch configmap course-tutor-release-metadata \
  --type merge -p '{"data":{"verification-result":"passed"}}' >/dev/null

jq -n \
  --arg release "${release}" --arg namespace "${namespace}" \
  --arg environment "${environment}" --arg actor "${GITHUB_ACTOR:-local}" \
  --arg revision "$(helm history "${release}" -n "${namespace}" -o json | jq -r '.[-1].revision')" \
  --arg release_sha "$(jq -r .release_sha "${manifest}")" \
  --arg verified_at "$(date -u +%Y-%m-%dT%H:%M:%SZ)" \
  '{release: $release, namespace: $namespace, environment: $environment, actor: $actor,
    helm_revision: $revision, release_sha: $release_sha, verification: "passed",
    verified_at: $verified_at}' > "${record_dir}/deployment-${environment}.json"

cat "${record_dir}/deployment-${environment}.json"
