#!/usr/bin/env bash
set -euo pipefail

usage() {
  cat <<'EOF'
Usage: scripts/local-real-kind-setup.sh --host-path PATH [--cluster NAME]

Creates (but never replaces) a Kind cluster whose node sees PATH read-only at
/mnt/course-content, then creates the course-tutor namespace and a static read-only
PV/PVC. Existing clusters are accepted only when their mount is already present.
EOF
}

cluster_name="course-tutor-real"
host_path=""
while (($#)); do
  case "$1" in
    --host-path) host_path="${2:?missing value for --host-path}"; shift 2 ;;
    --cluster) cluster_name="${2:?missing value for --cluster}"; shift 2 ;;
    -h|--help) usage; exit 0 ;;
    *) echo "Unknown argument: $1" >&2; usage >&2; exit 2 ;;
  esac
done

[[ -n "$host_path" ]] || { echo "--host-path is required" >&2; exit 2; }
[[ "$host_path" = /* ]] || { echo "--host-path must be absolute" >&2; exit 2; }
[[ -d "$host_path" && -r "$host_path" ]] || {
  echo "Course directory is missing or unreadable: $host_path" >&2
  exit 1
}

for command in kind kubectl jq docker python3; do
  command -v "$command" >/dev/null || { echo "$command is required" >&2; exit 1; }
done

COURSE_TUTOR_HOST_PATH="$host_path" python3 - <<'PY'
import os
import signal

def timed_out(_signum, _frame):
    raise TimeoutError

signal.signal(signal.SIGALRM, timed_out)
signal.alarm(10)
try:
    first = next(os.scandir(os.environ["COURSE_TUTOR_HOST_PATH"]), None)
except TimeoutError:
    raise SystemExit("course directory did not respond in 10s; reconnect the NAS mount")
finally:
    signal.alarm(0)
if first is None:
    raise SystemExit("course directory is empty; refusing to bind it")
PY

if ! kind get clusters | grep -Fxq "$cluster_name"; then
  config_file="$(mktemp -t course-tutor-kind.XXXXXX)"
  trap 'rm -f "$config_file"' EXIT
  jq -n --arg host "$host_path" '{
    kind: "Cluster",
    apiVersion: "kind.x-k8s.io/v1alpha4",
    nodes: [{role: "control-plane", extraMounts: [{
      hostPath: $host,
      containerPath: "/mnt/course-content",
      readOnly: true
    }]}]
  }' >"$config_file"
  kind create cluster --name "$cluster_name" --config "$config_file"
fi

context="kind-$cluster_name"
kubectl config use-context "$context" >/dev/null
node="${cluster_name}-control-plane"
if ! docker exec "$node" test -d /mnt/course-content; then
  echo "Existing Kind cluster '$cluster_name' has no /mnt/course-content mount." >&2
  echo "Choose a new --cluster name; this script will not delete or replace a cluster." >&2
  exit 1
fi

kubectl create namespace course-tutor --dry-run=client -o yaml | kubectl apply -f -
kubectl apply -f - <<'EOF'
apiVersion: v1
kind: PersistentVolume
metadata:
  name: course-tutor-content
spec:
  capacity:
    storage: 10Gi
  accessModes: [ReadOnlyMany]
  persistentVolumeReclaimPolicy: Retain
  storageClassName: course-tutor-local
  hostPath:
    path: /mnt/course-content
    type: Directory
---
apiVersion: v1
kind: PersistentVolumeClaim
metadata:
  name: course-tutor-content
  namespace: course-tutor
spec:
  accessModes: [ReadOnlyMany]
  storageClassName: course-tutor-local
  volumeName: course-tutor-content
  resources:
    requests:
      storage: 10Gi
EOF

kubectl wait --namespace course-tutor --for=jsonpath='{.status.phase}'=Bound \
  pvc/course-tutor-content --timeout=60s
echo "Kind context $context is ready with Bound PVC course-tutor/course-tutor-content."
