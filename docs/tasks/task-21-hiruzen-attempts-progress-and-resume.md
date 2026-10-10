# TASK-21 — Hiruzen Attempts, Progress and Resume

**Status:** complete (2026-10-10)
**Priority:** P0  
**Depends on:** TASK-19, TASK-20

## Goal

Provide deterministic submissions, the accepted three-attempt answer-release policy,
derived study progress and authorization-safe resume.

## Scope

- Persist immutable attempts, evaluator provenance and idempotent activity events.
- Implement objective grading and provisional rubric-constrained short-answer grading.
- Reveal progressive hints after attempts one/two and answer/rationale after attempt
  three or explicit give-up.
- Project study status/mastery and maintain a safe resume cursor.
- Add learner question reports and compact consent-aware Agent memory signals.

## Deliverable artifacts

| Artifact | Repository path |
|---|---|
| Attempt/progress/resume persistence migration | `apps/practice/alembic/versions/*_attempts_progress.py` |
| Attempt and study domain policies | `apps/practice/src/course_tutor_practice/domain/{attempts,study,policies}.py` |
| Grading and progress projection services | `apps/practice/src/course_tutor_practice/application/{evaluation,progress}.py` |
| Attempt/progress/resume/report routes | `apps/practice/src/course_tutor_practice/routes/{attempts,progress,reports}.py` |
| Updated Practice contracts/OpenAPI | `packages/contracts/src/course_tutor_contracts/practice.py`, `packages/contracts/openapi/practice-api.v1.json` |
| Release-policy and security matrices | `tests/integration/practice/` |
| Projection/rebuild unit tests | `apps/practice/tests/` |
| Completion evidence | `docs/verification/<date>-task-21.md` |

## Acceptance criteria

- **AC-21.1:** Replayed submissions cannot inflate attempts, completion or score.
- **AC-21.2:** Attempt one and two return progressively stronger hints without protected
  answers; attempt three or explicit give-up releases answer and rationale.
- **AC-21.3:** Answers cannot be obtained early through PracticeSet, feedback, report,
  progress or resume APIs.
- **AC-21.4:** Resume returns the latest still-authorized safe position and falls back
  safely when access is removed.
- **AC-21.5:** Progress can be rebuilt solely from immutable attempts and activity events.
- **AC-21.6:** Objective and provisional short-answer evaluation retain evaluator provenance,
  and migration/security/projection tests pass.

## Independent delivery boundary

TASK-21 owns attempt, grading, release, progress and resume APIs. It consumes immutable
PracticeSets from TASK-20 and must not change generation or Agent evidence contracts.

## Verification

```bash
uv run pytest apps/practice/tests tests/integration/practice -q
uv run pytest tests/integration/security -q
uv run python scripts/validate_hiruzen_baseline.py
```

For observable API acceptance, use a `READY` set and its exercise IDs from
`GET /v1/practice/sets/{set_id}`. Submit to
`POST /v1/practice/sets/{set_id}/exercises/{exercise_id}/attempts` with a distinct
`Idempotency-Key` for each answer; repeating the same key must return the same attempt.
The first two incorrect responses have `hint` but `released_answer: null`; the third
incorrect response or `POST .../give-up` contains the answer and cited rationale.
`GET /v1/practice/study-status` and `GET /v1/practice/resume` show only safe progress
and navigation. `DELETE /v1/practice/resume` clears the cursor without deleting history.

Build and deployment remain the project-wide process in the root README. The API
and Practice worker require the `p210001` Practice migration before startup. The
currently checked-in Helm topology does **not** deploy the independent Practice worker
or migration; this is TASK-23 and does not affect the isolated TASK-21 API/test gate.
Acceptance evidence: [2026-10-10-task-21.md](../verification/2026-10-10-task-21.md).
