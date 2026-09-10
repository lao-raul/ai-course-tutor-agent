# TASK-05 — Safe Integration Tests and RAG Evaluation

**Status:** complete (2026-09-10)
**Priority:** P0
**Depends on:** TASK-02, TASK-03, TASK-04

## Goal

Make test results meaningful and ensure no integration test can erase the developer’s live course database.

## Scope

- Replace the current localhost/live-DB integration fixture with Testcontainers or Compose-created disposable PostgreSQL, Redis, Qdrant and MinIO instances.
- Add a mandatory database marker/name check before any destructive cleanup.
- Correct the stale `database_url`/`postgres_dsn` setting and NAS mount path mismatch.
- Keep all CI fixtures generated or copyright-cleared; never require the home NAS or LAN LM Studio service.
- Convert `tests/retrieval_benchmark.py` from a data generator into an executable benchmark.
- Measure Recall@k, MRR, citation precision, abstention precision/recall and latency; store machine-readable results as CI artifacts.
- Add Agent API contract tests, frontend tests, ingestion lifecycle tests, ACL tests and SSE ordering tests.
- Add a minimal end-to-end flow: create fixture course → ingest → embed → publish → ask → verify grounded citation.
- Add regression tests for every P0/P1 issue found during the September review.

## Deliverables

- Safe integration-test harness and generated fixtures.
- Automated RAG benchmark with documented thresholds.
- CI-readable JUnit/coverage/benchmark reports.
- Test inventory mapped to the requirements traceability table.

## Acceptance criteria

- Tests refuse to execute destructive SQL against the normal `course_tutor` database.
- CI runs all integration tests without NAS or LM Studio.
- A synthetic benchmark actually invokes retrieval and fails below agreed thresholds.
- Chat, access control, citation mapping, version readiness and repeated ingestion all have regression coverage.
- Unit/integration/e2e suites are distinguishable and independently runnable.

## Verification

```bash
uv run pytest tests/unit -q
uv run pytest tests/integration -q
uv run pytest tests/e2e -q
uv run python tests/retrieval_benchmark.py --output build/rag-metrics.json
```
