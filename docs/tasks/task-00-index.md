# Delivery Task Index

**Status:** v0.2 complete; Hiruzen v0.3 delivery active
**Objective:** evolve the current prototype into a tested, Helm-packaged Kubernetes
platform with two backend applications.

## Target deployables

1. **Agent API** — the existing `apps/api` codebase: course ingestion administration, grounded course chat, citations, sessions and learner memory.
2. **Practice API / Hiruzen** — the current `apps/practice` dummy reserves the boundary;
   TASK-18–TASK-24 evolve it into the independently deployed catalog, practice,
   attempts/progress and resume product defined by the accepted v0.3 specifications.
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
| 17 | [TASK-17](task-17-persistent-k12-storage-and-deduplication.md) | complete (2026-09-16) | P0 | Persistent state, NAS snapshots and content-addressed K-12 ingestion | TASK-03, TASK-09, TASK-12, TASK-16 |
| 18 | [TASK-18](task-18-hiruzen-catalog-contract-and-import.md) | complete (2026-10-07) | P0 | Agent-owned ChinaTextbook catalog, staged import and Hiruzen catalog facade | TASK-17 |
| 19 | [TASK-24](task-24-agent-textbook-outline-extraction-and-api.md) | complete (2026-10-09) | P0 | Agent-owned deterministic textbook outline extraction and API | TASK-15, TASK-18 |
| 20 | [TASK-19](task-19-hiruzen-persistence-and-generation-jobs.md) | complete (2026-10-08) | P0 | Practice schema, default StudyPlan and asynchronous generation jobs | TASK-18; parallel with TASK-24 |
| 21 | [TASK-20](task-20-hiruzen-grounded-generation.md) | complete (2026-10-10) | P0 | Delegated evidence API and validated grounded question generation | TASK-18, TASK-19 |
| 22 | [TASK-21](task-21-hiruzen-attempts-progress-and-resume.md) | complete (2026-10-10) | P0 | Attempts, release policy, progress and safe resume | TASK-19, TASK-20 |
| 23 | [TASK-22](task-22-hiruzen-chat-and-web-experience.md) | complete (2026-10-10) | P1 | Book discovery, practice UI and direct Agent tutoring chat | TASK-18–TASK-21, TASK-24 |
| 24 | [TASK-23](task-23-hiruzen-deployment-and-quality-gates.md) | planned | P0 | Independent workloads, CI/E2E and golden-set quality gates | TASK-18–TASK-22, TASK-24 |

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
summary and regression testing on 2026-09-13. TASK-17 completed persistent stateful
Helm storage, NAS-backed Qdrant snapshots, staged ingestion and content-addressed
cross-version source/vector reuse on 2026-09-16.

TASK-18 completed the Agent-owned ChinaTextbook catalog, worker-only staged scanning,
review/approval activation, published-book queries, tenant-authenticated system CourseRuns
and the HTTP-only Hiruzen catalog facade on 2026-10-07, unblocking TASK-19 and TASK-24.
TASK-19 completed the isolated Practice schema, default StudyPlans, protected Exercise
contract, idempotent generation jobs and lease-safe worker boundary on 2026-10-08.
TASK-24 completed deterministic Agent outline extraction, persistence and the authorized
versioned outline API on 2026-10-09. TASK-20 completed delegated, version-pinned Agent
evidence retrieval, structured generation, deterministic validation and the redacted
Chen Lin Grade 3 real-model pilot on 2026-10-10. TASK-21 completed immutable,
idempotent submissions, staged answer release, grading provenance, rebuildable progress,
authorization-safe resume and consent-gated compact memory signals on 2026-10-10.
TASK-22 completed the Hiruzen Web flow, direct Agent SSE tutoring, language selection,
safe feedback/resume UI and generated-fixture browser/accessibility checks on
2026-10-10. TASK-23 is now the remaining Hiruzen task; its independent workload and
real-model release gates are not covered by the TASK-22 fixture tests.

The accepted Hiruzen v0.3 expansion starts at TASK-18. Its specialist requirements,
operation boundary and verification mapping are maintained in
[`apps/practice/docs/requirements-traceability.md`](../../apps/practice/docs/requirements-traceability.md)
and checked independently from the completed v0.2 baseline.

## Global rules

- No real NAS documents, SMB credentials, kubeconfig, LM Studio key or production secret may enter Git history or CI artifacts.
- Production startup must fail when authentication is disabled or placeholder secrets are used.
- CI must not call the home NAS or LAN LM Studio instance; it uses generated fixtures and deterministic fake services.
- Database integration tests must use a disposable database and must refuse to run against an unmarked database.
- Kubernetes resources use immutable image tags/digests; `latest` is not a deployable release identifier.
- Helm is the supported Kubernetes packaging and release interface. Source templates,
  packaged chart and deployed revision must represent the same validated chart version.
- Documentation completion claims must be supported by an automated check or a linked, dated manual verification record.
- Every Hiruzen task must retain sequential `AC-<task>.<n>` acceptance criteria,
  path-addressable deliverable artifacts and explicit verification; the Hiruzen
  baseline validator enforces this structure.
