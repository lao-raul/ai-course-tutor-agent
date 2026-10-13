#!/usr/bin/env bash
set -euo pipefail

# Upgrade Practice Worker (optionally Practice API) in an existing local Kind
# release, then run a real HTTP generation audit. Persistent data stays untouched.
repo_root="$(cd "$(dirname "${BASH_SOURCE[0]}")/.." && pwd)"
book_id="${PRACTICE_PILOT_BOOK_ID:?PRACTICE_PILOT_BOOK_ID is required}"
: "${COURSE_TUTOR_AUTH_TOKEN:?COURSE_TUTOR_AUTH_TOKEN is required}"
cluster_name="course-tutor-hiruzen"
image_tag=""
skip_build=false
with_practice_api=false

while (($#)); do
  case "$1" in
    --cluster) cluster_name="${2:?missing value for --cluster}"; shift 2 ;;
    --tag) image_tag="${2:?missing value for --tag}"; shift 2 ;;
    --skip-build) skip_build=true; shift ;;
    --with-practice-api) with_practice_api=true; shift ;;
    *) echo "Unknown argument: $1" >&2; exit 2 ;;
  esac
done

if [[ -z "$image_tag" ]]; then
  revision="$(git -C "$repo_root" rev-parse --short HEAD)"
  image_tag="practice-qa-${revision}-$(date +%Y%m%d%H%M%S)"
fi
context="kind-$cluster_name"
image="course-tutor-practice-worker:$image_tag"
practice_image="course-tutor-practice:$image_tag"
kubectl --context "$context" -n course-tutor get deployment course-tutor-practice-worker >/dev/null
if [[ "$with_practice_api" == true ]]; then
  kubectl --context "$context" -n course-tutor get deployment course-tutor-practice-api >/dev/null
fi
helm --kube-context "$context" -n course-tutor status course-tutor >/dev/null

if [[ "$skip_build" == false ]]; then
  bake_targets=(practice-worker)
  if [[ "$with_practice_api" == true ]]; then
    bake_targets+=(practice-api)
  fi
  TAG="$image_tag" "$repo_root/scripts/build-docker.sh" "${bake_targets[@]}"
else
  docker image inspect "$image" >/dev/null
  if [[ "$with_practice_api" == true ]]; then
    docker image inspect "$practice_image" >/dev/null
  fi
fi
kind load docker-image --name "$cluster_name" "$image"
helm_image_args=(
  --set-string "practiceWorker.image.tag=$image_tag"
  --set-string 'practiceWorker.image.digest='
)
if [[ "$with_practice_api" == true ]]; then
  kind load docker-image --name "$cluster_name" "$practice_image"
  helm_image_args+=(
    --set-string "backend.practice.image.tag=$image_tag"
    --set-string 'backend.practice.image.digest='
  )
fi
helm --kube-context "$context" upgrade course-tutor \
  "$repo_root/infra/k8s/course-tutor" \
  -n course-tutor --reuse-values "${helm_image_args[@]}" \
  --wait --wait-for-jobs --timeout 10m
kubectl --context "$context" -n course-tutor rollout status \
  deployment/course-tutor-practice-worker --timeout=5m
if [[ "$with_practice_api" == true ]]; then
  kubectl --context "$context" -n course-tutor rollout status \
    deployment/course-tutor-practice-api --timeout=5m
fi

forward_log="$(mktemp)"
kubectl --context "$context" -n course-tutor port-forward \
  --address 127.0.0.1 service/course-tutor-practice 28001:8001 \
  >"$forward_log" 2>&1 &
forward_pid=$!
cleanup() {
  kill "$forward_pid" >/dev/null 2>&1 || true
  wait "$forward_pid" 2>/dev/null || true
  rm -f "$forward_log"
}
trap cleanup EXIT

for _ in $(seq 1 30); do
  if ! kill -0 "$forward_pid" 2>/dev/null; then
    cat "$forward_log" >&2
    exit 1
  fi
  if curl -fsS --max-time 2 http://127.0.0.1:28001/healthz >/dev/null 2>&1; then
    break
  fi
  sleep 1
done
curl -fsS --max-time 3 http://127.0.0.1:28001/healthz >/dev/null

probe_args=(
  --book-id "$book_id"
  --count "${PRACTICE_PILOT_COUNT:-20}"
  --timeout "${PRACTICE_PILOT_TIMEOUT:-600}"
)
if [[ -n "${PRACTICE_PILOT_MODULE_ID:-}" ]]; then
  probe_args+=(--module-id "$PRACTICE_PILOT_MODULE_ID")
fi
if [[ -n "${PRACTICE_PILOT_QUESTION_TYPE:-}" ]]; then
  probe_args+=(--question-type "$PRACTICE_PILOT_QUESTION_TYPE")
fi
"$repo_root/.venv/bin/python" "$repo_root/scripts/verify_practice_generation_api.py" \
  "${probe_args[@]}"
