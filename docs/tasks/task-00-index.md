# Delivery Task Index

**Status:** ready
**Objective:** evolve the current prototype into a tested, Helm-packaged Kubernetes
platform with two backend applications.

## Target deployables

1. **Agent API** — the existing `apps/api` codebase: course ingestion administration, grounded course chat, citations, sessions and learner memory.
2. **Practice API** — a new `apps/practice` dummy application that reserves the contract and deployment boundary for future random exercise generation.
3. **Supporting workloads** — ingestion worker and React Web UI. These are not counted as additional backend product apps.

The existing `apps/api` path and `course_tutor_api` package name remain unchanged for now. Its image, Kubernetes workload and service are named `course-tutor-agent-api`. This avoids a large rename that does not improve runtime separation.

## Recommended execution order

| Order | Task | Priority | Main outcome | Depends on |
|---:|---|---|---|---|
| 1 | [TASK-01](task-01-requirements-and-contract-baseline.md) | P0 | Approved v0.2 requirements and contracts | — |
| 2 | [TASK-02](task-02-agent-security-and-resource-lifecycle.md) | P0 | Server-derived authorization and safe dependency lifecycle | TASK-01 |
| 3 | [TASK-03](task-03-ingestion-and-content-version-lifecycle.md) | P0 | Repeatable periodic NAS ingestion and publish lifecycle | TASK-01 |
| 4 | [TASK-04](task-04-rag-correctness-and-streaming.md) | P0 | Correct citations, ACL-filtered retrieval and real streaming | TASK-02, TASK-03 |
| 5 | [TASK-05](task-05-safe-tests-and-rag-evaluation.md) | P0 | Disposable integration tests and measurable RAG gates | TASK-02–04 |
| 6 | [TASK-06](task-06-agent-memory-and-teaching-policy.md) | P1 | Multi-turn and compact long-term memory | TASK-02, TASK-04 |
| 7 | [TASK-07](task-07-practice-api-dummy-app.md) | P1 | Second backend app with stable dummy contract | TASK-01, TASK-02 |
| 8 | [TASK-08](task-08-container-packaging.md) | P0 | Reproducible images for all workloads | TASK-02–04, TASK-07 |
| 9 | [TASK-09](task-09-kubernetes-helm-deployment.md) | P0 | Helm-based Kubernetes deployment | TASK-08 |
| 10 | [TASK-10](task-10-github-actions-ci.md) | P0 | CI including ephemeral cluster deployment test | TASK-05, TASK-08, TASK-09 |
| 11 | [TASK-11](task-11-github-actions-cd.md) | P1 | GHCR publication and controlled cluster rollout | TASK-09, TASK-10 |
| 12 | [TASK-12](task-12-observability-ha-and-release-readiness.md) | P1 | SLOs, resilience, runbooks and release gate | TASK-06, TASK-09–11 |

Tasks may be implemented in separate branches and merged independently once their declared dependencies are present. A task is complete only when all acceptance criteria and verification steps in its file pass.

**Progress:** TASK-01, TASK-02 and TASK-03 completed on 2026-09-09. TASK-04,
TASK-05, TASK-07, TASK-08 and TASK-09 completed locally on 2026-09-10. TASK-10 is
implemented and passed its local equivalent; its first GitHub-hosted run remains
pending a user-controlled commit/push. TASK-06, TASK-11 and TASK-12 remain open.

## Global rules

- No real NAS documents, SMB credentials, kubeconfig, LM Studio key or production secret may enter Git history or CI artifacts.
- Production startup must fail when authentication is disabled or placeholder secrets are used.
- CI must not call the home NAS or LAN LM Studio instance; it uses generated fixtures and deterministic fake services.
- Database integration tests must use a disposable database and must refuse to run against an unmarked database.
- Kubernetes resources use immutable image tags/digests; `latest` is not a deployable release identifier.
- Helm is the supported Kubernetes packaging and release interface. Source templates,
  packaged chart and deployed revision must represent the same validated chart version.
- Documentation completion claims must be supported by an automated check or a linked, dated manual verification record.
