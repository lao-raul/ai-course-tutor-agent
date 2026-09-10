# TASK-09 — Kubernetes and Helm Deployment

**Status:** complete (2026-09-10)
**Priority:** P0
**Depends on:** TASK-08

## Goal

Create the single supported Helm package for installing, upgrading and rolling back
both backend apps and their supporting workloads on Kubernetes.

## Scope

- Create one Helm v3 application chart under `infra/k8s/course-tutor` with independently configurable Agent API, Practice API, ingestion worker and Web workloads. Do not maintain a parallel set of handwritten release manifests.
- Add semantic chart versioning, a distinct `appVersion`, `values.schema.json`, chart notes and labels/annotations that identify the chart and application versions.
- Add Deployment/Service resources, probes, resource requests/limits, security contexts, service accounts, pod anti-affinity/topology spread and rolling-update strategy.
- Add PodDisruptionBudgets and optional HPAs for stateless APIs; worker scales by configured replicas/queue metrics.
- Keep PostgreSQL, Qdrant, Redis and MinIO configurable as external endpoints in production. Supply CI/dev dependencies through a clearly non-production values file.
- Mount course content through an existing read-only PVC. Support SMB CSI configuration via values/Secret references without storing credentials in Git.
- Configure LM Studio as an external URL; CI substitutes the fake-LLM service.
- Use ConfigMaps for non-secret settings and Secret references/external-secret integration for credentials.
- Add NetworkPolicies limiting ingress and egress to required services.
- Add migration Job with hook/order semantics so only one migration runs per rollout.
- Add `values-ci.yaml`, `values-local.yaml` and production example values without secrets.
- Validate manifests with Helm lint/template plus schema/policy validation.
- Package the exact validated chart with `helm package`; make the archive available to
  CI/CD for optional publication to a GHCR OCI chart repository.
- Document `helm upgrade --install --atomic --wait`, `helm test`, release history and
  `helm rollback` commands. Kubernetes deployment must not depend on manual `kubectl apply`.

## Deliverables

- Versioned Helm chart, packaged `.tgz` artifact, values schema and deployment documentation.
- Kind-compatible CI configuration.
- Upgrade/rollback and NAS PVC setup instructions.

## Acceptance criteria

- `helm package` creates `course-tutor-<chart-version>.tgz` from the validated source chart.
- `helm upgrade --install --atomic --wait` deploys both backend apps and the worker into a clean Kind namespace.
- All pods become Ready and run as non-root.
- Agent and Practice Services are independently addressable.
- A failed new image does not remove all ready replicas and can be rolled back.
- Production values contain no inline secret values or local host paths.
- Course PVC is mounted read-only only by workloads that require source access.
- A Helm test pod verifies Agent and Practice health endpoints, and `helm rollback`
  restores a previously healthy revision after a deliberately failed upgrade.
- `helm template` is deterministic for identical chart, values and image digests.

## Verification

```bash
helm lint infra/k8s/course-tutor
helm template course-tutor infra/k8s/course-tutor -f infra/k8s/course-tutor/values-ci.yaml
helm package infra/k8s/course-tutor --destination build/charts
helm upgrade --install course-tutor infra/k8s/course-tutor --namespace course-tutor --create-namespace --atomic --wait -f infra/k8s/course-tutor/values-ci.yaml
helm test course-tutor --namespace course-tutor
scripts/kind-smoke-test.sh
```
