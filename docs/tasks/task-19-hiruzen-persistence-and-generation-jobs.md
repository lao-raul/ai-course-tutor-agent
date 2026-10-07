# TASK-19 — Hiruzen Persistence and Generation Jobs

**Status:** planned  
**Priority:** P0  
**Depends on:** TASK-18

## Goal

Replace the dummy Practice persistence boundary with a separately owned `practice`
schema, default Book study plans and an idempotent asynchronous generation state machine.

## Scope

- Add StudyPlan/module, GenerationJob, PracticeSet and protected Exercise persistence.
- Derive a read-only default Book → StudyPlan → Chapter/Topic plan from Agent-provided
  PDF outline metadata; fall back to one book-level module with no invented objectives.
- Add transactional outbox/worker leases, deadlines, retries and cancellation.
- Keep answer/rationale storage out of learner read models.
- Add create/status/set operations to the versioned Practice OpenAPI contract.

## Deliverable artifacts

| Artifact | Repository path |
|---|---|
| Practice persistence models/session boundary | `apps/practice/src/course_tutor_practice/db/` |
| Initial Practice schema migration | `apps/practice/alembic/versions/*_practice_schema.py` |
| StudyPlan and protected Exercise domain models | `apps/practice/src/course_tutor_practice/domain/` |
| Canonical four-type Exercise DTO/JSON Schema | `packages/contracts/src/course_tutor_contracts/practice.py` |
| Generation command/state machine | `apps/practice/src/course_tutor_practice/application/generation.py` |
| Generation and PracticeSet routes | `apps/practice/src/course_tutor_practice/routes/{generations,practice_sets}.py` |
| Worker entrypoint and outbox consumer | `services/practice_worker/` |
| Updated Practice OpenAPI | `packages/contracts/openapi/practice-api.v1.json` |
| Unit/integration tests | `apps/practice/tests/`, `tests/integration/practice/` |
| Completion evidence | `docs/verification/<date>-task-19.md` |

## Acceptance criteria

- **AC-19.1:** Practice database role cannot read Agent tables and no cross-schema foreign keys exist.
- **AC-19.2:** Replayed idempotency keys return the original job and PracticeSet.
- **AC-19.3:** Worker crash or lease expiry is safe under at-least-once delivery.
- **AC-19.4:** Learner PracticeSet DTOs cannot serialize protected answer fields.
- **AC-19.5:** A missing authored plan produces one deterministic default Book StudyPlan
  from Agent outline metadata, or one book-level fallback module, without inventing
  chapters or learning objectives.
- **AC-19.6:** Migration upgrade/downgrade, state-machine and OpenAPI contract tests pass.
- **AC-19.7:** Book-based generation defaults to five questions, accepts 1–20 and the
  deprecated v0.2 course endpoint resolves to the same idempotent command.

## Independent delivery boundary

TASK-19 owns the Practice schema, canonical Exercise contract, default StudyPlan and
job lifecycle. It uses fake Agent/evidence providers and does not implement retrieval or
LLM generation; TASK-20 fills those ports without changing persisted job semantics.

## Verification

```bash
uv run pytest apps/practice/tests tests/integration/practice -q
uv run alembic -c apps/practice/alembic.ini upgrade head
uv run python scripts/validate_hiruzen_baseline.py
```

The integration harness must use a disposable marked PostgreSQL database and perform
an upgrade/downgrade/upgrade round trip.
