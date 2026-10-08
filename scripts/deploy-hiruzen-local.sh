#!/usr/bin/env bash
set -euo pipefail

usage() {
  cat <<'EOF'
Usage: scripts/deploy-hiruzen-local.sh [options]

Build and deploy the real Hiruzen/ChinaTextbook stack to a dedicated Kind cluster.

Required environment variables:
  COURSE_TUTOR_AUTH_TOKEN       Local bearer token used by Agent and Practice
  COURSE_TUTOR_MINIO_SECRET     MinIO secret for the local dependency

Optional environment variables:
  LLM_BASE_URL                  Defaults to http://192.168.50.146:1234/v1
  LLM_CHAT_MODEL                Defaults to qwen/qwen3.6-35b-a3b
  LLM_EMBEDDING_MODEL           Defaults to text-embedding-qwen3-embedding-0.6b
  LLM_EMBEDDING_DIMENSION       Defaults to 1024
  LM_STUDIO_API_KEY             Defaults to an empty local key

Options:
  --host-path PATH              NAS mount (default: /Volumes/home/ChinaTextbook)
  --cluster NAME                Kind cluster (default: course-tutor-hiruzen)
  --values FILE                 Additional local Helm values file
  --tag TAG                     Image tag (default: unique task18 local tag)
  --skip-build                  Reuse already-built local images with --tag
  -h, --help                    Show this help

Example:
  export COURSE_TUTOR_AUTH_TOKEN='replace-with-local-token'
  export COURSE_TUTOR_MINIO_SECRET='replace-with-random-secret'
  scripts/deploy-hiruzen-local.sh
EOF
}

repo_root="$(cd "$(dirname "${BASH_SOURCE[0]}")/.." && pwd)"
host_path="/Volumes/home/ChinaTextbook"
cluster_name="course-tutor-hiruzen"
namespace="course-tutor"
release="course-tutor"
values_file=""
image_tag=""
skip_build=false

while (($#)); do
  case "$1" in
    --host-path) host_path="${2:?missing value for --host-path}"; shift 2 ;;
    --cluster) cluster_name="${2:?missing value for --cluster}"; shift 2 ;;
    --values) values_file="${2:?missing value for --values}"; shift 2 ;;
    --tag) image_tag="${2:?missing value for --tag}"; shift 2 ;;
    --skip-build) skip_build=true; shift ;;
    -h|--help) usage; exit 0 ;;
    *) echo "Unknown argument: $1" >&2; usage >&2; exit 2 ;;
  esac
done

auth_token="${COURSE_TUTOR_AUTH_TOKEN:?COURSE_TUTOR_AUTH_TOKEN is required}"
minio_secret="${COURSE_TUTOR_MINIO_SECRET:?COURSE_TUTOR_MINIO_SECRET is required}"
llm_base_url="${LLM_BASE_URL:-http://192.168.50.146:1234/v1}"
chat_model="${LLM_CHAT_MODEL:-qwen/qwen3.6-35b-a3b}"
embedding_model="${LLM_EMBEDDING_MODEL:-text-embedding-qwen3-embedding-0.6b}"
embedding_dimension="${LLM_EMBEDDING_DIMENSION:-1024}"
llm_api_key="${LM_STUDIO_API_KEY:-}"
runtime_secret="course-tutor-local-runtime"

[[ "$host_path" = /* ]] || { echo "--host-path must be absolute" >&2; exit 2; }
[[ -d "$host_path" && -r "$host_path" ]] || {
  echo "ChinaTextbook directory is missing or unreadable: $host_path" >&2
  exit 1
}
[[ "$llm_base_url" == */v1 ]] || {
  echo "LLM_BASE_URL must end with /v1: $llm_base_url" >&2
  exit 2
}
[[ "$embedding_dimension" =~ ^[1-9][0-9]*$ ]] || {
  echo "LLM_EMBEDDING_DIMENSION must be a positive integer" >&2
  exit 2
}
if [[ -n "$values_file" && ! -f "$values_file" ]]; then
  echo "Additional values file does not exist: $values_file" >&2
  exit 2
fi
if [[ "$skip_build" == true && -z "$image_tag" ]]; then
  echo "--skip-build requires an explicit --tag" >&2
  exit 2
fi

for command in curl docker kind kubectl helm jq; do
  command -v "$command" >/dev/null || { echo "$command is required" >&2; exit 1; }
done

echo "==> Checking configured models against LM Studio before building"
curl_headers=(-H "Content-Type: application/json")
if [[ -n "$llm_api_key" ]]; then
  curl_headers+=(-H "Authorization: Bearer $llm_api_key")
fi
if ! models_json="$(
  curl -fsS --max-time 15 "${curl_headers[@]}" "$llm_base_url/models"
)"; then
  echo "Cannot reach LM Studio models endpoint: $llm_base_url/models" >&2
  echo "Confirm that the LM Studio server is running and reachable from this host." >&2
  exit 1
fi
if ! jq -e '.data | type == "array"' >/dev/null <<<"$models_json"; then
  echo "LM Studio returned an invalid /models response:" >&2
  jq . <<<"$models_json" >&2 || true
  exit 1
fi

missing_models=()
if ! jq -e --arg model "$chat_model" 'any(.data[]; .id == $model)' \
  >/dev/null <<<"$models_json"; then
  missing_models+=("$chat_model")
fi
if ! jq -e --arg model "$embedding_model" 'any(.data[]; .id == $model)' \
  >/dev/null <<<"$models_json"; then
  missing_models+=("$embedding_model")
fi
if ((${#missing_models[@]})); then
  echo "Configured LM Studio model IDs are not loaded:" >&2
  printf '  - %s\n' "${missing_models[@]}" >&2
  echo "Available model IDs:" >&2
  jq -r '.data[]?.id | "  - \(.)"' <<<"$models_json" >&2
  echo "Export exact IDs with LLM_CHAT_MODEL and LLM_EMBEDDING_MODEL, then rerun." >&2
  exit 2
fi

embedding_payload="$(jq -nc --arg model "$embedding_model" \
  '{model: $model, input: ["course tutor host preflight"]}')"
if ! embedding_json="$(
  curl -fsS --max-time 90 "${curl_headers[@]}" \
    --data "$embedding_payload" "$llm_base_url/embeddings"
)"; then
  echo "LM Studio embedding request failed for model: $embedding_model" >&2
  exit 1
fi
actual_dimension="$(jq -r 'try (.data[0].embedding | length) catch empty' \
  <<<"$embedding_json")"
if [[ -z "$actual_dimension" || "$actual_dimension" == "null" ]]; then
  echo "LM Studio returned no embedding vector for model: $embedding_model" >&2
  jq . <<<"$embedding_json" >&2 || true
  exit 1
fi
if [[ "$actual_dimension" != "$embedding_dimension" ]]; then
  echo "Embedding dimension mismatch: configured=$embedding_dimension actual=$actual_dimension" >&2
  echo "Export LLM_EMBEDDING_DIMENSION=$actual_dimension and rerun." >&2
  exit 2
fi
echo "PASS chat_model=$chat_model embedding_model=$embedding_model dimension=$actual_dimension"

if [[ -z "$image_tag" ]]; then
  revision="$(git -C "$repo_root" rev-parse --short HEAD 2>/dev/null || echo unknown)"
  image_tag="task18-${revision}-$(date +%Y%m%d%H%M%S)"
fi

images=(
  "course-tutor-agent:$image_tag"
  "course-tutor-practice:$image_tag"
  "course-tutor-worker:$image_tag"
  "course-tutor-web:$image_tag"
)

echo "==> Preparing Kind cluster $cluster_name with read-only source $host_path"
"$repo_root/scripts/local-real-kind-setup.sh" \
  --host-path "$host_path" \
  --cluster "$cluster_name"
kubectl config use-context "kind-$cluster_name" >/dev/null

if [[ "$skip_build" == false ]]; then
  echo "==> Building application images with tag $image_tag"
  TAG="$image_tag" "$repo_root/scripts/build-docker.sh" \
    agent-api practice-api ingestion-worker web
else
  echo "==> Reusing application images with tag $image_tag"
  for image in "${images[@]}"; do
    docker image inspect "$image" >/dev/null || {
      echo "Local image is missing: $image" >&2
      exit 1
    }
  done
fi

echo "==> Loading images into Kind cluster $cluster_name"
kind load docker-image --name "$cluster_name" "${images[@]}"

echo "==> Applying runtime Secret in $namespace"
kubectl -n "$namespace" create secret generic "$runtime_secret" \
  --from-literal=local-auth-token="$auth_token" \
  --from-literal=minio-access-key=course-tutor \
  --from-literal=minio-secret-key="$minio_secret" \
  --from-literal=llm-api-key="$llm_api_key" \
  --dry-run=client -o yaml | kubectl apply -f - >/dev/null

echo "==> Running NAS and LM Studio preflight"
NAMESPACE="$namespace" \
RELEASE="$release" \
RUNTIME_SECRET="$runtime_secret" \
LLM_BASE_URL="$llm_base_url" \
LLM_CHAT_MODEL="$chat_model" \
LLM_EMBEDDING_MODEL="$embedding_model" \
LLM_EMBEDDING_DIMENSION="$embedding_dimension" \
PREFLIGHT_IMAGE="course-tutor-agent:$image_tag" \
  "$repo_root/scripts/local-real-preflight.sh"

values_args=(
  --values "$repo_root/infra/k8s/course-tutor/values-local-real.example.yaml"
)
if [[ -n "$values_file" ]]; then
  values_args+=(--values "$values_file")
fi

config_args=(
  --set-string "config.llmBaseUrl=$llm_base_url"
  --set-string "config.llmChatModel=$chat_model"
  --set-string "config.llmEmbeddingModel=$embedding_model"
  --set "config.llmEmbeddingDimension=$embedding_dimension"
  # The dedicated Kind cluster has no NAS-backed snapshot PVC. Production and
  # long-lived local environments must enable this with a provisioned claim.
  --set "internalDependencies.qdrant.snapshots.enabled=false"
  --set-string "backend.agent.image.tag=$image_tag"
  --set-string "backend.practice.image.tag=$image_tag"
  --set-string "worker.image.tag=$image_tag"
  --set-string "web.image.tag=$image_tag"
)

deployment_diagnostics() {
  echo "==> Deployment failed; collecting diagnostics" >&2
  helm status "$release" -n "$namespace" >&2 || true
  kubectl get pods,jobs,pvc -n "$namespace" -o wide >&2 || true

  local backend_pod
  backend_pod="$(
    kubectl -n "$namespace" get pods \
      -l app.kubernetes.io/component=backend \
      -o jsonpath='{.items[0].metadata.name}' 2>/dev/null || true
  )"
  if [[ -n "$backend_pod" ]]; then
    kubectl -n "$namespace" get pod "$backend_pod" -o json \
      | jq '[.status.containerStatuses[]? | {name, ready, state, restartCount}]' >&2 || true
    kubectl -n "$namespace" exec "$backend_pod" -c agent-api -- \
      python -c $'import urllib.error, urllib.request\nurl = "http://127.0.0.1:8000/readyz"\ntry:\n    response = urllib.request.urlopen(url, timeout=10)\n    print(response.status, response.read().decode())\nexcept urllib.error.HTTPError as error:\n    print(error.code, error.read().decode())' >&2 || true
    kubectl -n "$namespace" logs "$backend_pod" -c agent-api --tail=100 >&2 || true
    kubectl -n "$namespace" logs "$backend_pod" -c practice-api --tail=50 >&2 || true
  fi
  kubectl get events -n "$namespace" --sort-by=.lastTimestamp \
    | tail -60 >&2 || true
}

echo "==> Validating Helm values"
helm lint "$repo_root/infra/k8s/course-tutor" \
  "${values_args[@]}" \
  "${config_args[@]}"

echo "==> Installing Helm release $release"
if ! helm upgrade --install "$release" "$repo_root/infra/k8s/course-tutor" \
  --namespace "$namespace" \
  --create-namespace \
  "${values_args[@]}" \
  "${config_args[@]}" \
  --set-string "global.buildRevision=$(git -C "$repo_root" rev-parse --short HEAD)" \
  --wait \
  --wait-for-jobs \
  --timeout 10m; then
  deployment_diagnostics
  exit 1
fi

# Images normally trigger the application rollout. Explicit restarts also make an
# updated out-of-band runtime Secret take effect when --skip-build reuses a tag.
kubectl rollout restart \
  deployment/${release}-backend \
  deployment/${release}-worker \
  deployment/${release}-minio \
  -n "$namespace"
kubectl rollout status deployment/${release}-backend -n "$namespace" --timeout=5m
kubectl rollout status deployment/${release}-worker -n "$namespace" --timeout=5m
kubectl rollout status deployment/${release}-minio -n "$namespace" --timeout=5m

echo "==> Verifying deployed mounts, dependencies and LM Studio"
NAMESPACE="$namespace" \
RELEASE="$release" \
RUNTIME_SECRET="$runtime_secret" \
LLM_BASE_URL="$llm_base_url" \
LLM_CHAT_MODEL="$chat_model" \
LLM_EMBEDDING_MODEL="$embedding_model" \
LLM_EMBEDDING_DIMENSION="$embedding_dimension" \
PREFLIGHT_IMAGE="course-tutor-agent:$image_tag" \
  "$repo_root/scripts/local-real-preflight.sh"

backend_pod="$(
  kubectl -n "$namespace" get pods \
    -l app.kubernetes.io/component=backend \
    -o jsonpath='{.items[0].metadata.name}'
)"

echo "==> Verifying Agent and Practice readiness from the deployed Pod"
kubectl -n "$namespace" exec "$backend_pod" -c agent-api -- \
  python -c 'import urllib.request; print(urllib.request.urlopen("http://127.0.0.1:8000/readyz", timeout=10).read().decode())'
kubectl -n "$namespace" exec "$backend_pod" -c practice-api -- \
  python -c 'import urllib.request; print(urllib.request.urlopen("http://127.0.0.1:8001/readyz", timeout=10).read().decode())'

helm status "$release" -n "$namespace"
kubectl get pods -n "$namespace" -o wide

cat <<EOF

Hiruzen local deployment completed successfully.
  Kind context: kind-$cluster_name
  Helm release: $namespace/$release
  Image tag:    $image_tag
  NAS source:   $host_path -> /data/content (read-only)

Open API documentation in separate terminals:
  kubectl -n $namespace port-forward service/${release}-agent 18000:8000
  kubectl -n $namespace port-forward service/${release}-practice 18001:8001

Then visit:
  http://127.0.0.1:18000/docs
  http://127.0.0.1:18001/docs
EOF
