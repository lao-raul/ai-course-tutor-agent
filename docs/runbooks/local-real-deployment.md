# Local-real deployment runbook

This profile connects a dedicated Kind cluster to an already-mounted read-only course
tree and to LM Studio on the LAN. It never stores an SMB password, API token, private
course path or course document in Git.

## 1. Host and LM Studio prerequisites

Mount the NAS with Finder or your credential manager and identify the host path that
contains the selected module directories. Do not put the SMB URL or password in Helm
values. Before creating the cluster, verify that listing one file returns promptly;
a mounted but disconnected SMB share can pass `test -d` while directory reads hang.

In LM Studio:

1. Load one chat model and one embedding model.
2. Enable the OpenAI-compatible server on port `1234` and allow connections beyond
   loopback.
3. Permit inbound TCP/1234 in the host firewall.
4. Use an address reachable from Docker/Kind and include `/v1` in `llmBaseUrl`.

Model IDs must exactly match `GET /v1/models`. The configured embedding dimension
must equal the vector length returned by `POST /v1/embeddings`; the preflight rejects
a mismatch before ingestion can create an incompatible index.

## 2. Create a non-destructive Kind storage boundary

The setup command creates `course-tutor-real` only if it does not exist. It never
deletes or replaces another cluster.

```bash
scripts/local-real-kind-setup.sh \
  --host-path "/absolute/host/path/to/University of Leeds/modules"
```

The Kind node receives the path at `/mnt/course-content` with a read-only bind. A
static `course-tutor-content` PV/PVC exposes it only to workloads selected by the Helm
chart. For a multi-node/non-Kind cluster, provision an equivalent `ReadOnlyMany` PVC
with the SMB CSI driver and keep its credential reference in a Kubernetes Secret.

## 3. Create untracked runtime configuration

Create the runtime Secret without writing its values to a file:

```bash
kubectl -n course-tutor create secret generic course-tutor-local-runtime \
  --from-literal=local-auth-token="$COURSE_TUTOR_AUTH_TOKEN" \
  --from-literal=minio-access-key=course-tutor \
  --from-literal=minio-secret-key="$COURSE_TUTOR_MINIO_SECRET" \
  --from-literal=llm-api-key="$LM_STUDIO_API_KEY" \
  --dry-run=client -o yaml | kubectl apply -f -
```

Copy the placeholder profile to `.local/course-tutor.values.yaml` and replace only
the endpoint and model fields. `.local/` is ignored by Git.

```bash
mkdir -p .local
cp infra/k8s/course-tutor/values-local-real.example.yaml .local/course-tutor.values.yaml
```

## 4. Build, load, preflight and install

```bash
TAG=local scripts/build-docker.sh
kind load docker-image --name course-tutor-real \
  course-tutor-agent:local course-tutor-practice:local \
  course-tutor-worker:local course-tutor-web:local

export LLM_BASE_URL=http://LAN_HOST:1234/v1
export LLM_CHAT_MODEL=exact-loaded-chat-model
export LLM_EMBEDDING_MODEL=exact-loaded-embedding-model
export LLM_EMBEDDING_DIMENSION=1024
scripts/local-real-preflight.sh

helm lint infra/k8s/course-tutor \
  -f infra/k8s/course-tutor/values-local-real.example.yaml \
  -f .local/course-tutor.values.yaml
helm upgrade --install course-tutor infra/k8s/course-tutor \
  --namespace course-tutor --create-namespace \
  -f infra/k8s/course-tutor/values-local-real.example.yaml \
  -f .local/course-tutor.values.yaml \
  --atomic --wait --wait-for-jobs --timeout 10m
scripts/local-real-preflight.sh
```

The second preflight additionally proves that Agent API and worker can read but not
write the volume, Practice API and Web do not mount it, and no fake LLM Deployment is
present.

## 5. Operate and recover

```bash
helm status course-tutor -n course-tutor
kubectl get pvc,pods -n course-tutor
kubectl logs -n course-tutor deploy/course-tutor-worker
helm history course-tutor -n course-tutor
helm rollback course-tutor REVISION -n course-tutor --wait
```

If the PVC stays Pending, check that the PV name, storage class and namespace match.
If file reads hang, unmount and reconnect the SMB share before recreating a *new* Kind
cluster name. If LM Studio fails from inside the cluster but works on the host, check
its bind address, firewall and the LAN/Docker route. Never point CI at this profile.
