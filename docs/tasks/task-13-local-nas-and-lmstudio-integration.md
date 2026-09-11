# TASK-13 — Local NAS and LM Studio Integration

**Status:** ready
**Priority:** P0
**Depends on:** TASK-03, TASK-04, TASK-09

## Goal

Run the local Kubernetes release against the real read-only Leeds course-material
tree and the LAN-hosted LM Studio service, without weakening the deterministic CI
profile or committing private infrastructure details and credentials.

## Scope

- Define and document one repeatable macOS/Kind storage path for course material:
  either a pre-provisioned SMB CSI PersistentVolumeClaim or a Kind node mount backed
  by the host-mounted NAS directory.
- Keep SMB credentials in a Kubernetes Secret or external secret store. Do not place
  credentials, course files or a user-specific mount path in tracked values files.
- Add a safe local-real Helm values example and a documented untracked override for:
  `courseContent.enabled`, `courseContent.existingClaim`, LM Studio base URL, chat
  model, embedding model and embedding dimension.
- Disable the fake LLM whenever the local-real profile is selected. CI must continue
  to use its deterministic fake provider and generated fixtures.
- Add preflight checks that fail clearly when the source directory is absent, the PVC
  is not Bound, the volume is writable from an application container, model metadata
  is incompatible, or LM Studio cannot be reached from inside the cluster.
- Mount course material read-only only into the Agent API and ingestion worker. The
  Practice API, Web UI and internal dependencies must not receive the course volume.
- Document network requirements for LM Studio, including listening beyond loopback,
  firewall access and the `/v1` OpenAI-compatible endpoint.
- Provide install, upgrade, verification and rollback commands for the local-real
  profile without changing the default CI installation path.

## Deliverables

- Local-real example values containing placeholders only.
- Kind/SMB CSI PVC setup instructions and any non-secret reusable manifests or scripts.
- A preflight/verification script for volume permissions and in-cluster LM Studio
  connectivity.
- An updated Helm deployment runbook describing troubleshooting and rollback.

## Acceptance criteria

- A clean local Kind cluster can bind the configured course-content PVC and deploy the
  Helm release using documented commands.
- Agent API and worker can recursively read the configured modules directory, and a
  write attempt from either workload fails.
- Practice API and Web pods do not mount the course-content volume.
- Fake LLM resources are absent from the local-real release.
- From the Agent pod, LM Studio model discovery, one embedding request and one bounded
  chat request succeed using the configured model names and embedding dimension.
- The tracked repository, rendered manifests and Helm release metadata contain no SMB
  password, LM Studio key, course document or machine-specific secret override.
- `values-ci.yaml` and GitHub Actions remain independent of the NAS and LAN service.

## Verification

```bash
helm lint infra/k8s/course-tutor -f infra/k8s/course-tutor/values-local-real.example.yaml
helm template course-tutor infra/k8s/course-tutor \
  -f infra/k8s/course-tutor/values-local-real.example.yaml
scripts/local-real-preflight.sh
helm upgrade --install course-tutor infra/k8s/course-tutor \
  --namespace course-tutor --create-namespace \
  -f infra/k8s/course-tutor/values-local-real.example.yaml \
  -f .local/course-tutor.values.yaml --atomic --wait
```

Completion requires a dated local verification record identifying the Helm revision,
PVC name, redacted LM Studio endpoint and successful preflight checks. It must not
contain credentials or course content.
