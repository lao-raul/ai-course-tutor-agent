# TASK-12 — Observability, High Availability and Release Readiness

**Status:** ready
**Priority:** P1
**Depends on:** TASK-06, TASK-09, TASK-10, TASK-11

## Goal

Demonstrate that the platform can be operated, scaled and recovered rather than merely deployed.

## Scope

- Define end-user SLOs for Agent chat, Practice API, ingestion freshness and memory deletion; clarify how LM Studio availability affects the service SLO.
- Export request, retrieval, LLM, queue, ingestion and memory metrics with bounded-cardinality labels.
- Propagate correlation/trace IDs across Web, both APIs, worker, database, Qdrant and LM Studio calls.
- Add readiness probes for every required dependency, including MinIO where artifacts are required.
- Add retry budgets, timeouts and circuit breakers; distinguish dependency degradation from process liveness.
- Validate stateless API horizontal scaling and locked/idempotent worker scaling.
- Add PostgreSQL backup/PITR guidance, Qdrant snapshots, object-store backup and restore drills with RPO/RTO targets.
- Add alerts and runbooks for LM Studio outage, ingestion backlog/dead letter, retrieval regression, database saturation and failed rollout.
- Add load and failure-injection tests; record capacity baseline and bottlenecks.
- Reconcile README/spec completion statuses with verified results and create a release checklist.

## Deliverables

- Metrics/tracing configuration and dashboards/alerts as code.
- Backup/restore, outage, rollout and data-deletion runbooks.
- Load/failure test reports and release checklist.
- Updated Function/Design specs with final traceability evidence.

## Acceptance criteria

- Loss of one Agent or Practice API pod does not interrupt availability through the Service.
- A worker restart or duplicate event does not duplicate indexed data.
- LM Studio failure returns a bounded user-safe error and raises an actionable signal.
- A documented restore drill meets declared RPO/RTO.
- Memory deletion and content rollback are observable and auditable.
- Release readiness can be decided from automated evidence, not README claims.

## Verification

- Run the load/failure suite against a non-production Kubernetes namespace.
- Terminate one replica of each workload during traffic and verify SLO behavior.
- Perform and document a restore and Helm rollback drill.
