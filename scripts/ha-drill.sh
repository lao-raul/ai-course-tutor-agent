#!/usr/bin/env bash
set -euo pipefail

namespace="${NAMESPACE:-course-tutor}"
deployment="${BACKEND_DEPLOYMENT:-course-tutor-backend}"
output="${HA_DRILL_OUTPUT:-build/reports/ha-drill.json}"
requests="${HA_DRILL_REQUESTS:-300}"

original_replicas="$(kubectl -n "${namespace}" get deployment "${deployment}" -o jsonpath='{.spec.replicas}')"
cleanup() {
  kubectl -n "${namespace}" delete pod course-tutor-ha-load --ignore-not-found --wait=false >/dev/null 2>&1 || true
  kubectl -n "${namespace}" scale deployment "${deployment}" --replicas="${original_replicas}" >/dev/null 2>&1 || true
}
trap cleanup EXIT

if (( original_replicas < 2 )); then
  kubectl -n "${namespace}" scale deployment "${deployment}" --replicas=2
fi
kubectl -n "${namespace}" rollout status deployment/"${deployment}" --timeout=5m

load_image="$(kubectl -n "${namespace}" get deployment "${deployment}" \
  -o json | jq -r '.spec.template.spec.containers[] | select(.name == "agent-api") | .image')"
load_program='import json,time,urllib.request
failures=[]
urls=["http://course-tutor-agent:8000/healthz","http://course-tutor-practice:8001/healthz"]
start=time.time()
for i in range(int(__import__("os").environ["REQUESTS"])):
  for url in urls:
    try:
      with urllib.request.urlopen(url,timeout=2) as r:
        if r.status != 200: failures.append({"url":url,"status":r.status})
    except Exception as exc: failures.append({"url":url,"error":type(exc).__name__})
  time.sleep(.02)
print(json.dumps({"requests":int(__import__("os").environ["REQUESTS"])*2,"failures":len(failures),"elapsed_seconds":round(time.time()-start,3),"sample":failures[:5]}))
raise SystemExit(1 if failures else 0)'

kubectl -n "${namespace}" run course-tutor-ha-load \
  --image="${load_image}" --restart=Never \
  --env="REQUESTS=${requests}" --command -- python -c "${load_program}"
kubectl -n "${namespace}" wait pod/course-tutor-ha-load --for=condition=Ready --timeout=2m
victim="$(kubectl -n "${namespace}" get pods -l app.kubernetes.io/component=backend \
  -o jsonpath='{.items[0].metadata.name}')"
kubectl -n "${namespace}" delete pod "${victim}" --wait=false

if ! kubectl -n "${namespace}" wait pod/course-tutor-ha-load --for=jsonpath='{.status.phase}'=Succeeded --timeout=5m; then
  kubectl -n "${namespace}" logs course-tutor-ha-load >&2 || true
  exit 1
fi
mkdir -p "$(dirname "${output}")"
kubectl -n "${namespace}" logs course-tutor-ha-load | tail -1 > "${output}"
jq -e '.failures == 0' "${output}" >/dev/null
kubectl -n "${namespace}" rollout status deployment/"${deployment}" --timeout=5m
cat "${output}"
