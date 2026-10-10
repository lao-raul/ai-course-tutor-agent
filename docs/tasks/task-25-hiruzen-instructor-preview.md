# TASK-25 — Hiruzen Instructor Preview

**Status:** planned
**Priority:** P1
**Depends on:** TASK-18–TASK-22
**Can run in parallel with:** TASK-23

## Goal

Complete HFR-GEN-10 with a privileged, read-only preview of generated PracticeSets.
An authorized instructor can inspect the question, protected answer/rationale, rubric
and textbook citations before deciding whether it is suitable for teaching. Preview
does **not** turn AI-generated content into an official assessment or publish it.

## Scope

- Implement the already specified `previewPracticeSet` operation at
  `GET /v1/practice/sets/{set_id}/preview` with a dedicated response contract.
- Authorize against the authenticated tenant, the exact Book/Course binding and an
  instructor role with course access. Deny learners and unassigned teaching assistants
  by default; any broader role policy needs an explicit, reviewed decision.
- Include protected answers only in this privileged read model. Keep learner
  `getPracticeSet`, generation, attempt, resume and chat responses unchanged.
- Show the immutable content version, question revision, citation IDs and validation
  provenance. Resolve evidence only through authorized Agent interfaces; never mount
  or browse the NAS from Hiruzen.
- Record a redacted audit event for each successful preview, including actor, tenant,
  set, content version, timestamp and correlation ID, but no answer text or PDF content.
- Add an instructor-only Web preview with an unmistakable AI-generated/not-official
  label and read-only behavior. No approval, publication or assessment-authority
  workflow is included in this task.

## Deliverable artifacts

| Artifact | Repository path |
|---|---|
| Privileged preview and audit contracts | `packages/contracts/src/course_tutor_contracts/practice.py`, `packages/contracts/openapi/practice-api.v1.json` |
| Practice preview authorization/read model | `apps/practice/src/course_tutor_practice/routes/preview.py`, `apps/practice/src/course_tutor_practice/application/preview.py` |
| Redacted audit persistence/migration | `apps/practice/src/course_tutor_practice/db/`, `apps/practice/alembic/versions/` |
| Instructor-only preview UI and typed client | `apps/web/src/features/instructor/`, `apps/web/src/api/practice.ts` |
| Role, tenant, answer-leakage and audit tests | `apps/practice/tests/`, `tests/integration/practice/`, `apps/web/tests/e2e/hiruzen/` |
| Dated, redacted verification record | `docs/verification/<date>-task-25.md` |

## Acceptance criteria

- **AC-25.1:** A course-authorized instructor can preview a READY PracticeSet pinned to
  its exact Book/Course/content version, including answers, rationale, rubric and
  citation/provenance metadata. Unpublished, inaccessible or missing sets fail closed.
- **AC-25.2:** Student, cross-tenant and unassigned staff requests cannot obtain a
  preview. Existing learner endpoints still contain no protected answer material;
  cache and error responses do not leak it either.
- **AC-25.3:** Each successful preview records a redacted, attributable audit event.
  Logs, traces and audit payloads never contain answer keys, raw textbook passages or
  learner submissions.
- **AC-25.4:** The Web preview is discoverable only to authorized instructors, clearly
  labels every item AI-generated/not official, and offers no automatic publication or
  official-assessment action.
- **AC-25.5:** Disposable integration and browser tests cover allowed/denied roles,
  version pinning, response isolation, audit redaction and UI labeling. The OpenAPI
  contract and Hiruzen baseline validator pass.

## Independent delivery boundary

TASK-25 implements the instructor-preview requirement only. It does not change the
learner practice/release policy, introduce an assessment publishing workflow or modify
TASK-23's deployment/quality-gate scope. It can be built independently after its
declared dependencies are present and does not block the first learner release gate.

## Verification

When implemented, run the new preview unit/integration tests against disposable
Practice storage, then run:

```bash
uv run python scripts/validate_hiruzen_baseline.py
uv run python scripts/validate_openapi.py
npm --prefix apps/web test
npm --prefix apps/web run test:e2e
```

The dated evidence must include one authorized preview, explicit student/cross-tenant
denials, an audit record inspection and proof that learner responses remain answer-free.
