# TASK-11 — GitHub Actions Continuous Delivery

**Status:** ready
**Priority:** P1
**Depends on:** TASK-09, TASK-10

## Goal

Publish immutable images and deploy the Helm release through controlled environments with verification and rollback.

## Scope

- On protected main/tag releases, build once and push Agent API, Practice API, worker and Web images to GHCR using immutable Git SHA tags and digests.
- Sign images/provenance and publish SBOMs where supported.
- Use GitHub Environments for development/staging/production approvals and environment-specific values.
- Authenticate to the target cluster through OIDC/workload identity or a narrowly scoped deployment credential; never commit kubeconfig.
- Deploy the exact tested image digests with `helm upgrade --install --atomic --wait`.
- Run post-deploy smoke tests against both backend apps and one minimal Agent RAG flow appropriate to the environment.
- Record chart version, image digests, actor, environment and verification result.
- Automatically roll back failed development/staging rollouts; require explicit production policy approval.
- Support manual redeploy/rollback to a previously published immutable release.

## Configuration dependency

The actual cluster provider, registry namespace, ingress hostnames, certificate issuer and production secret manager are not yet specified. Implement the workflow as a reusable deployment workflow plus environment contract; activation of production CD waits for those values.

## Deliverables

- Image publication and deployment workflows.
- Environment configuration contract and release/rollback runbook.
- Post-deploy smoke-test script shared with CI.

## Acceptance criteria

- The deployed digest equals the digest built and tested in CI.
- Agent and Practice API rollouts are separately visible and verifiable.
- A failed readiness or smoke check leaves the last healthy release serving traffic.
- No long-lived broad cluster credential appears in repository secrets or logs.
- A previous release can be restored through a documented, tested command/workflow dispatch.

## Verification

- Deploy a release to a non-production environment and compare running pod image digests with the CI provenance record.
- Trigger a controlled failed rollout and verify automatic rollback plus smoke-test failure reporting.
- Dispatch a rollback to the previous immutable release and verify both backend apps become Ready.
