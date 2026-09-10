# TASK-01 — Requirements and Contract Baseline

**Status:** complete
**Priority:** P0
**Can run in parallel:** no; baseline task

## Goal

Publish an internally consistent v0.2 specification for a platform with an Agent API and a Practice API, and remove stale completion claims before further implementation.

## Scope

- Define the domain hierarchy: tenant/institution → programme → module/course → course run → content version.
- Define how NAS directories map to courses and whether one root may contain multiple modules.
- Specify file add/change/delete/rename behavior, scan cadence, manual rescan, version preview, publish and rollback.
- Mark `apps/api` as the Agent API deployable and reserve `apps/practice` for Practice API.
- Reconcile documented and actual endpoint names. Choose one canonical versioned API contract.
- Define the Practice API dummy behavior: health, readiness, capabilities and a not-implemented generation response.
- Define measurable acceptance targets for retrieval, citations, streaming latency, memory, availability, RPO/RTO and deployment smoke tests.
- Resolve contradictions where Phase 1/2 are marked complete while open decisions still block their exit gates.
- Add an ADR for the two-app boundary and shared-course-data ownership.

## Required decisions

1. `apps/api` remains the source path; runtime identity is `agent-api`.
2. Agent API owns course/content metadata. Practice API consumes versioned course/retrieval contracts and does not create a second course database schema.
3. The initial Practice API is deliberately non-functional and returns `501 practice_generation_not_implemented` for generation requests.
4. Kubernetes packaging uses one Helm chart with independently enabled/scaled workloads.

## Deliverables

- Updated `docs/function-spec.md` and `docs/design-spec.md`, status v0.2.
- `docs/adr/004-two-backend-apps-and-data-ownership.md`.
- Versioned OpenAPI schemas for both backend apps under `packages/contracts` or generated contract artifacts.
- A requirements traceability table mapping each functional requirement to implementation task and test.

## Acceptance criteria

- Every documented endpoint matches an OpenAPI operation or is explicitly marked planned.
- Every “complete” claim links to automated verification or is downgraded to partial/planned.
- The recurring ingestion lifecycle and two-app ownership model can be implemented without an unresolved product choice.
- Security and memory requirements include concrete production defaults, not only general intentions.

## Verification

- Render both OpenAPI documents and validate them.
- Run a script/test that fails when the traceability table references an unknown task or operation ID.

## Completion evidence

- Completed 2026-09-09.
- Function and Design specifications published as Baseline v0.2.
- ADR-004 accepted; Agent and Practice OpenAPI v1 contracts added.
- `scripts/validate_contract_baseline.py` reports 40 requirements, 12 implementation tasks and 19 operations with complete cross-reference coverage.
- `tests/unit/test_contract_baseline.py`, Ruff and formatting checks pass.
