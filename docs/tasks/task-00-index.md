# Delivery Task Index

**Status:** complete for the defined v0.2 task set
**Objective:** evolve the current prototype into a tested, Helm-packaged Kubernetes
platform with two backend applications.

## Target deployables

1. **Agent API** — the existing `apps/api` codebase: course ingestion administration, grounded course chat, citations, sessions and learner memory.
2. **Practice API** — a new `apps/practice` dummy application that reserves the contract and deployment boundary for future random exercise generation.
3. **Supporting workloads** — ingestion worker and React Web UI. These are not counted as additional backend product apps.

The existing `apps/api` path and `course_tutor_api` package name remain unchanged for now. Its image, Kubernetes workload and service are named `course-tutor-agent-api`. This avoids a large rename that does not improve runtime separation.

## Recommended execution order

| Order | Task | Status | Priority | Main outcome | Depends on |
|---:|---|---|---|---|---|
| 1 | [TASK-01](task-01-requirements-and-contract-baseline.md) | complete (2026-09-09) | P0 | Approved v0.2 requirements and contracts | — |
| 2 | [TASK-02](task-02-agent-security-and-resource-lifecycle.md) | complete (2026-09-09) | P0 | Server-derived authorization and safe dependency lifecycle | TASK-01 |
| 3 | [TASK-03](task-03-ingestion-and-content-version-lifecycle.md) | complete (2026-09-09) | P0 | Repeatable periodic NAS ingestion and publish lifecycle | TASK-01 |
| 4 | [TASK-04](task-04-rag-correctness-and-streaming.md) | complete (2026-09-10) | P0 | Correct citations, ACL-filtered retrieval and real streaming | TASK-02, TASK-03 |
| 5 | [TASK-05](task-05-safe-tests-and-rag-evaluation.md) | complete (2026-09-10) | P0 | Disposable integration tests and measurable RAG gates | TASK-02–04 |
| 6 | [TASK-06](task-06-agent-memory-and-teaching-policy.md) | complete (2026-09-10) | P1 | Multi-turn and compact long-term memory | TASK-02, TASK-04 |
| 7 | [TASK-07](task-07-practice-api-dummy-app.md) | complete (2026-09-10) | P1 | Second backend app with stable dummy contract | TASK-01, TASK-02 |
| 8 | [TASK-08](task-08-container-packaging.md) | complete (2026-09-10) | P0 | Reproducible images for all workloads | TASK-02–04, TASK-07 |
| 9 | [TASK-09](task-09-kubernetes-helm-deployment.md) | complete (2026-09-10) | P0 | Helm-based Kubernetes deployment | TASK-08 |
| 10 | [TASK-10](task-10-github-actions-ci.md) | complete (2026-09-14) | P0 | CI including ephemeral cluster deployment test | TASK-05, TASK-08, TASK-09 |
| 11 | [TASK-11](task-11-github-actions-cd.md) | complete (2026-09-15) | P1 | GHCR publication and controlled cluster rollout | TASK-09, TASK-10 |
| 12 | [TASK-12](task-12-observability-ha-and-release-readiness.md) | complete (2026-09-15) | P1 | SLOs, resilience, runbooks and release gate | TASK-06, TASK-09–11 |
| 13 | [TASK-13](task-13-local-nas-and-lmstudio-integration.md) | complete (2026-09-13) | P0 | Real NAS/PVC and LM Studio integration for local Kubernetes | TASK-03, TASK-04, TASK-09 |
| 14 | [TASK-14](task-14-course-bootstrap-and-e2e-validation.md) | complete (2026-09-13) | P0 | Idempotent Leeds course onboarding and browser-level validation | TASK-03, TASK-04, TASK-13 |
| 15 | [TASK-15](task-15-rich-math-output-and-pdf-text-quality.md) | complete (2026-09-13) | P1 | Safe Markdown/TeX answers and page-accurate PDF citations | TASK-03, TASK-04, TASK-14 |
| 16 | [TASK-16](task-16-typed-unit-scope-and-summary-retrieval.md) | complete (2026-09-13) | P0 | Typed Unit/Week scope filtering and reliable scoped summaries | TASK-04, TASK-14 |

Tasks may be implemented in separate branches and merged independently once their declared dependencies are present. A task is complete only when all acceptance criteria and verification steps in its file pass.

**Progress:** TASK-01, TASK-02 and TASK-03 completed on 2026-09-09. TASK-04–09
completed locally by 2026-09-10. TASK-10 received successful hosted CI evidence on
2026-09-14. TASK-11–12 completed their immutable-delivery contracts, telemetry,
availability, restore and rollback validation on 2026-09-15; activating production CD
still requires the target provider/identity/secret configuration. TASK-13–14 completed
their dedicated Kind, real NAS, LM Studio, ingestion, publication, API and browser
acceptance on 2026-09-13. TASK-15 completed the rich mathematical answer and PDF
text-quality corrections discovered during that browser validation on 2026-09-13.
TASK-16 corrected the Unit 2 versus Week 2 retrieval collision and passed real-course
summary and regression testing on 2026-09-13.

## Global rules

- No real NAS documents, SMB credentials, kubeconfig, LM Studio key or production secret may enter Git history or CI artifacts.
- Production startup must fail when authentication is disabled or placeholder secrets are used.
- CI must not call the home NAS or LAN LM Studio instance; it uses generated fixtures and deterministic fake services.
- Database integration tests must use a disposable database and must refuse to run against an unmarked database.
- Kubernetes resources use immutable image tags/digests; `latest` is not a deployable release identifier.
- Helm is the supported Kubernetes packaging and release interface. Source templates,
  packaged chart and deployed revision must represent the same validated chart version.
- Documentation completion claims must be supported by an automated check or a linked, dated manual verification record.
