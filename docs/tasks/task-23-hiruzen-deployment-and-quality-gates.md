# TASK-23 — Hiruzen Deployment and Quality Gates

**Status:** in progress — code complete; isolated Kind and human-approved real golden set pending
**Priority:** P0  
**Depends on:** TASK-18–TASK-22, TASK-24

## Goal

Deploy Hiruzen API and worker as independent scalable workloads and make release quality
measurable through CI, Kind and a human-approved FLTRP golden set.

## Scope

- Split the transition sidecar into independent Hiruzen API and worker Deployments.
- Add Services, resources, probes, HPA/PDB and least-privilege NetworkPolicies.
- Ensure Hiruzen workloads never mount ChinaTextbook; only Agent ingestion does.
- Add generated-fixture CI E2E and real-pilot manual acceptance.
- Define and enforce groundedness, ambiguity, duplicate and latency gates.

## Deliverable artifacts

| Artifact | Repository path |
|---|---|
| Independent Hiruzen API/worker Helm templates | `infra/k8s/course-tutor/templates/{practice-api,practice-worker}-deployment.yaml` |
| Hiruzen Services, HPA/PDB and NetworkPolicies | `infra/k8s/course-tutor/templates/` |
| Chart values/schema and environment overlays | `infra/k8s/course-tutor/{values.yaml,values.schema.json,values-ci.yaml,values-local.yaml}` |
| Practice worker container/release build | `services/practice_worker/Dockerfile`, `docker-bake.hcl` |
| Hosted CI and release gates | `.github/workflows/{ci,release,deploy}.yml` |
| Kind and post-deploy E2E checks | `scripts/kind-smoke-test.sh`, `scripts/post-deploy-smoke.sh`, `tests/e2e/hiruzen/` |
| Golden-set benchmark and thresholds | `tests/evaluation/hiruzen/` |
| Release/quality evidence | `docs/verification/<date>-task-23.md`, `docs/release-checklist.md` |

## Acceptance criteria

- **AC-23.1:** API and worker are separate Deployments, scale independently and a worker
  restart loses no accepted job.
- **AC-23.2:** Helm/Kind tests prove workload isolation, required connectivity and that
  Hiruzen workloads have no ChinaTextbook volume mount.
- **AC-23.3:** CI uses generated fixtures/fake inference and cannot contact the home NAS
  or LAN LM Studio.
- **AC-23.4:** Images run non-root with immutable references, probes, resource limits,
  least-privilege policies and vulnerability gates.
- **AC-23.5:** The Chen Lin Grade-3-start Grade 3 first-term FLTRP golden set meets the
  measurable HNFR-1–HNFR-11 thresholds, and a dated release checklist records evidence
  or an explicit failed gate.
- **AC-23.6:** Helm install, upgrade, rollback and post-deploy smoke tests pass for the
  independent workload topology.

## Independent delivery boundary

Helm/CI skeleton work may start once TASK-19 fixes process entrypoints and dependencies;
TASK-23 does not change product APIs. Final quality/release acceptance waits for H1–H5,
including TASK-24's real outline contract used by the Chapter/Topic experience.

## Verification

```bash
helm lint infra/k8s/course-tutor
helm template course-tutor infra/k8s/course-tutor -f infra/k8s/course-tutor/values-ci.yaml
make kind-deploy
uv run python tests/evaluation/hiruzen/run.py --provider fake
```

Image security gates, failure drills and the dated redacted real golden-set report must
also pass before completion.

## Acceptance ledger (2026-10-10)

| Criterion | State | Evidence |
|---|---|---|
| AC-23.1 | independent local-real workloads Ready; recovery drill pending | Separate Deployments, lease heartbeat and SQL/in-memory reclaim tests; fresh Kind install/upgrade |
| AC-23.2 | local-real mount isolation verified; isolated CI replay pending | Fresh Kind preflight confirmed Practice has no content PVC; earlier dedicated Kind API timed out |
| AC-23.3 | automated | Generated fixture evaluation and CI fake inference; no NAS mount |
| AC-23.4 | render/build verified; published vulnerability scan pending | Non-root images, probes, resources, policies and Trivy workflow |
| AC-23.5 | **blocked on human review** | `golden_gate.py` fails closed without 20 reviewed real cases and dated approval |
| AC-23.6 | local-real install/upgrade/basic smoke passed; rollback and isolated replay pending | Fresh Kind revision 1→2, real citation and one READY PracticeSet; local-real Helm hooks disabled |

Never mark this task complete based solely on the synthetic fixture or a chart render.
