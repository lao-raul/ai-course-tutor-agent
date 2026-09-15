# TASK-10 — GitHub Actions Continuous Integration

**Status:** complete (2026-09-14)
**Priority:** P0
**Depends on:** TASK-05, TASK-08, TASK-09

## Goal

Make every pull request prove code quality, image buildability, Kubernetes installability and basic operation of both backend apps.

## Scope

- Preserve least-privilege workflow permissions and pin third-party actions to reviewed versions/SHAs.
- Add Python lint/format/typecheck/unit jobs and frontend lint/typecheck/unit/build jobs.
- Run safe integration/e2e tests against disposable services.
- Verify Alembic upgrade, downgrade where supported, re-upgrade and model/schema parity.
- Build all images with BuildKit cache; do not push on pull requests.
- Run secret, dependency, SBOM and container scans.
- Run Helm lint/template/schema/policy validation.
- Start a Kind cluster, load locally built images, install the chart with CI values and wait for rollouts.
- Execute smoke calls against both apps and the Web service.
- Upload test, coverage, RAG metric and deployment diagnostic artifacts on failure.
- Add concurrency cancellation and path-aware jobs without skipping required contract checks.

## Required smoke flow

1. Agent `/healthz` and `/readyz` return success.
2. Practice `/healthz`, `/readyz` and `/v1/practice/capabilities` return success.
3. Practice generation returns the expected 501 error contract.
4. A generated course fixture is ingested, embedded with fake embeddings, published and listed.
5. Agent chat returns ordered SSE events and a citation from the fixture.

## Acceptance criteria

- CI has no dependency on `/Volumes`, home NAS, LAN IPs or LM Studio.
- A deliberately broken Helm probe, migration, ACL test or API contract makes CI fail.
- Pull requests cannot report deployment success without completing the Kind smoke flow.
- Workflow artifacts contain no secrets or real course content.

## Verification

- Run the workflow on a branch with all jobs green.
- Run controlled negative tests for an invalid manifest and broken readiness endpoint.

## Local completion evidence

- The generated Kind fixture is mounted only into the worker, then registered, ingested,
  embedded by the deterministic fake provider, published, listed and queried by the Helm test.
- The Helm test validates Agent, Practice and Web health, Practice's 501 contract, and ordered
  `token -> citation -> done` SSE with a real fixture chunk UUID.
- `scripts/kind-negative-gates.sh` proves invalid values and an isolated broken-readiness
  Deployment fail, then removes the temporary negative-test resource.
- Five images built and the chart installed successfully in `course-tutor-local`; see the
  dated local verification record. The later hosted run below closed the remaining gate.

## Hosted completion evidence

GitHub-hosted CI completed successfully for main commit
`401ffcfdc3ad9110af8c968d958a86dbe6891858` in
[run 34798686954](https://github.com/lao-raul/ai-course-tutor-agent/actions/runs/34798686954).
This closes the hosted-verification item that remained after the local record.
