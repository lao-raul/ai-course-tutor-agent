# Release and rollback runbook

## Environment contract

Create protected GitHub Environments named `development`, `staging` and `production`.
Production must require reviewers. Each environment provides:

- secret `KUBE_CONFIG_B64`: base64-encoded, namespace-scoped deploy credential; replace
  this adapter with provider OIDC/workload identity when a cluster provider is chosen;
- secret `HELM_VALUES_B64`: base64-encoded environment values containing endpoint and
  existing-Secret references, never secret values;
- secret `SMOKE_BEARER_TOKEN`: short-lived token restricted to smoke-test access;
- variables `SMOKE_COURSE_ID`, `SMOKE_QUERY`, and `SMOKE_RAG_REQUIRED=true`.

The credential needs only Helm release resources in the target namespace. It must not
be cluster-admin and must be rotated. Kubeconfig files are materialized only under the
ephemeral runner directory and are never uploaded.

## Publish and deploy

Successful CI on `main` invokes `Publish immutable release`. It builds the four runtime
images once, pushes SHA tags and attached SBOM/provenance, signs each digest with
keyless cosign, packages the chart as `0.1.0-<short-sha>`, and uploads the release
manifest as evidence.

Run `Deploy or roll back immutable release` with `action=deploy`, the protected
environment, and the full published SHA. The workflow resolves the registry digests,
pulls the matching OCI chart, performs `helm upgrade --install --atomic --wait`, compares
every running image ID with the manifest, then tests Agent, Practice, Web, metrics and a
minimal RAG flow. Development/staging smoke failure rolls back automatically. Production
uses Helm atomic rollback for rollout failure, but post-rollout smoke rollback requires
the protected environment's explicit operator decision.

## Manual rollback

Inspect history, select a previously `deployed` revision and dispatch the workflow with
`action=rollback` and `rollback_revision=<number>`. The workflow executes Helm rollback
and repeats smoke tests. For an interactive non-production drill:

```bash
CONFIRM_NON_PRODUCTION=yes scripts/helm-rollback-drill.sh
```

The script proves both a readiness-failed atomic rollout and restoration of a previously
healthy revision. Preserve its JSON report with the release evidence.
