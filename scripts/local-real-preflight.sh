#!/usr/bin/env bash
set -euo pipefail

namespace="${NAMESPACE:-course-tutor}"
release="${RELEASE:-course-tutor}"
pvc="${COURSE_CONTENT_PVC:-course-tutor-content}"
mount_path="${COURSE_CONTENT_MOUNT_PATH:-/data/content}"
llm_base_url="${LLM_BASE_URL:?LLM_BASE_URL is required, including /v1}"
chat_model="${LLM_CHAT_MODEL:?LLM_CHAT_MODEL is required}"
embedding_model="${LLM_EMBEDDING_MODEL:?LLM_EMBEDDING_MODEL is required}"
embedding_dimension="${LLM_EMBEDDING_DIMENSION:?LLM_EMBEDDING_DIMENSION is required}"
runtime_secret="${RUNTIME_SECRET:-course-tutor-local-runtime}"
probe_image="${PREFLIGHT_IMAGE:-course-tutor-agent:local}"
pod="course-tutor-local-real-preflight"

for command in kubectl jq helm; do
  command -v "$command" >/dev/null || { echo "$command is required" >&2; exit 1; }
done
[[ "$llm_base_url" == */v1 ]] || { echo "LLM_BASE_URL must end with /v1" >&2; exit 1; }
[[ "$(kubectl -n "$namespace" get pvc "$pvc" -o jsonpath='{.status.phase}')" == "Bound" ]] || {
  echo "PVC $namespace/$pvc is not Bound" >&2
  exit 1
}
kubectl -n "$namespace" get secret "$runtime_secret" >/dev/null

read -r -d '' probe_code <<'PY' || true
import json
import os
import sys
import urllib.request

root = os.environ["COURSE_CONTENT_MOUNT_PATH"]
candidate = None
for current, _dirs, files in os.walk(root):
    for name in files:
        path = os.path.join(current, name)
        try:
            with open(path, "rb") as handle:
                handle.read(1)
            candidate = path
            break
        except OSError:
            continue
    if candidate:
        break
if candidate is None:
    raise RuntimeError(f"no readable course file below {root}")

probe_path = os.path.join(root, ".course-tutor-write-probe")
try:
    with open(probe_path, "wb") as handle:
        handle.write(b"must fail")
except OSError:
    pass
else:
    os.unlink(probe_path)
    raise RuntimeError("course volume is writable; refusing unsafe deployment")

base = os.environ["LLM_BASE_URL"].rstrip("/")
headers = {"Authorization": "Bearer " + os.environ.get("LLM_API_KEY", "")}
def request(path, body=None, timeout=60):
    data = None if body is None else json.dumps(body).encode()
    req = urllib.request.Request(
        base + path, data=data, headers={**headers, "Content-Type": "application/json"}
    )
    with urllib.request.urlopen(req, timeout=timeout) as response:
        return json.load(response)

models = {item["id"] for item in request("/models").get("data", [])}
required = {os.environ["LLM_CHAT_MODEL"], os.environ["LLM_EMBEDDING_MODEL"]}
if missing := required - models:
    raise RuntimeError(f"LM Studio models are not loaded: {sorted(missing)}")
embedding = request("/embeddings", {
    "model": os.environ["LLM_EMBEDDING_MODEL"], "input": ["course tutor preflight"]
})["data"][0]["embedding"]
expected = int(os.environ["LLM_EMBEDDING_DIMENSION"])
if len(embedding) != expected:
    raise RuntimeError(f"embedding dimension {len(embedding)} != configured {expected}")
request("/chat/completions", {
    "model": os.environ["LLM_CHAT_MODEL"],
    "messages": [{"role": "user", "content": "Reply with OK."}],
    "max_tokens": 8,
    "stream": False,
}, timeout=120)
print(f"PASS readable_file={os.path.relpath(candidate, root)!r} embedding_dimension={expected}")
PY

overrides="$(jq -nc \
  --arg image "$probe_image" --arg pvc "$pvc" --arg mount "$mount_path" \
  --arg base "$llm_base_url" --arg chat "$chat_model" --arg embedding "$embedding_model" \
  --arg dimension "$embedding_dimension" --arg secret "$runtime_secret" --arg code "$probe_code" '{
    apiVersion: "v1",
    spec: {
      restartPolicy: "Never",
      securityContext: {runAsNonRoot: true, runAsUser: 10001, runAsGroup: 10001},
      volumes: [{name: "course-content", persistentVolumeClaim: {claimName: $pvc, readOnly: true}}],
      containers: [{
        name: "probe", image: $image, imagePullPolicy: "IfNotPresent",
        command: ["python", "-c", $code],
        env: [
          {name: "COURSE_CONTENT_MOUNT_PATH", value: $mount},
          {name: "LLM_BASE_URL", value: $base},
          {name: "LLM_CHAT_MODEL", value: $chat},
          {name: "LLM_EMBEDDING_MODEL", value: $embedding},
          {name: "LLM_EMBEDDING_DIMENSION", value: $dimension},
          {name: "LLM_API_KEY", valueFrom: {secretKeyRef: {name: $secret, key: "llm-api-key"}}}
        ],
        volumeMounts: [{name: "course-content", mountPath: $mount, readOnly: true}],
        securityContext: {allowPrivilegeEscalation: false, readOnlyRootFilesystem: true, capabilities: {drop: ["ALL"]}}
      }]
    }
  }')"

kubectl -n "$namespace" delete pod "$pod" --ignore-not-found --wait >/dev/null
trap 'kubectl -n "$namespace" delete pod "$pod" --ignore-not-found --wait=false >/dev/null 2>&1 || true' EXIT
kubectl -n "$namespace" run "$pod" --image="$probe_image" --restart=Never --overrides="$overrides" >/dev/null

for _ in $(seq 1 120); do
  phase="$(kubectl -n "$namespace" get pod "$pod" -o jsonpath='{.status.phase}' 2>/dev/null || true)"
  [[ "$phase" == "Succeeded" || "$phase" == "Failed" ]] && break
  sleep 1
done
kubectl -n "$namespace" logs "$pod"
[[ "${phase:-}" == "Succeeded" ]] || {
  kubectl -n "$namespace" describe pod "$pod" >&2
  exit 1
}

if helm_status="$(helm status "$release" -n "$namespace" -o json 2>/dev/null)"; then
  [[ "$(jq -r '.info.status' <<<"$helm_status")" == "deployed" ]] || exit 1
  backend="$(kubectl -n "$namespace" get pod -l app.kubernetes.io/component=backend -o jsonpath='{.items[0].metadata.name}')"
  worker="$(kubectl -n "$namespace" get pod -l app.kubernetes.io/component=worker -o jsonpath='{.items[0].metadata.name}')"
  for target in "$backend:agent-api" "$worker:ingestion-worker"; do
    target_pod="${target%%:*}"; target_container="${target##*:}"
    kubectl -n "$namespace" exec "$target_pod" -c "$target_container" -- \
      python -c "import os; assert any(files for _,_,files in os.walk('$mount_path'))"
    if kubectl -n "$namespace" exec "$target_pod" -c "$target_container" -- \
      python -c "open('$mount_path/.course-tutor-write-probe','wb').close()" 2>/dev/null; then
      echo "$target_container can write course content" >&2
      exit 1
    fi
  done
  kubectl -n "$namespace" get pod "$backend" -o json | jq -e '
    (.spec.containers[] | select(.name == "practice-api") | .volumeMounts // [] |
      map(.name) | index("course-content")) == null' >/dev/null
  kubectl -n "$namespace" get deploy "${release}-web" -o json | jq -e '
    [.spec.template.spec.containers[].volumeMounts[]?.name] | index("course-content") == null' >/dev/null
  if kubectl -n "$namespace" get deploy,service \
    -l app.kubernetes.io/component=fake-llm -o name | grep -q .; then
    echo "fake LLM resources must be absent from a local-real release" >&2
    exit 1
  fi
  echo "PASS deployed workload mounts and fake-LLM isolation"
fi
