# TASK-07 — Practice API Dummy Application

**Status:** complete (2026-09-10)
**Priority:** P1
**Depends on:** TASK-01, TASK-02

## Goal

Create the second backend application as a small but production-shaped dummy service, without prematurely defining the exercise-generation algorithm.

## Scope

- Add `apps/practice` as an independent FastAPI package and deployable process.
- Reuse shared configuration, logging, tracing, correlation ID and authentication libraries without importing Agent API internals.
- Add `GET /healthz`, `GET /readyz` and `GET /v1/practice/capabilities`.
- Add `POST /v1/practice/courses/{course_id}/exercises:generate` with a minimal reserved request schema.
- Until product requirements are approved, return HTTP 501 with stable error code `practice_generation_not_implemented` and correlation ID.
- Verify authenticated tenant/course access without generating or persisting exercises.
- Publish a separate OpenAPI document and versioned container image.

## Non-goals

- Question-generation prompts, difficulty calibration, answer keys, grading, adaptive selection and attempt persistence.
- Copying retrieval or database business logic into the Practice API.

## Deliverables

- Practice API source, package metadata, tests and README.
- Versioned contracts/capabilities schema.
- Dockerfile and health/readiness behavior consumable by Kubernetes.

## Acceptance criteria

- The service starts without the Agent API process.
- Health and readiness return 200 under configured dependencies.
- Capabilities clearly report generation as unavailable.
- Generation returns deterministic 501, not a fake question.
- OpenAPI contains no internal Settings or secret-bearing schemas.

## Verification

```bash
uv run pytest apps/practice/tests -q
uv run uvicorn course_tutor_practice.app:create_app --factory --port 8001
```

## Completion evidence

- `apps/practice` is an independent FastAPI package and non-root container image.
- `packages/auth` is shared by Agent and Practice without importing Agent ORM/routes.
- Health, readiness, authenticated capabilities, course-scope failure and deterministic
  501 behavior are covered by `apps/practice/tests/test_app.py`.
- The checked-in Practice OpenAPI v1 operations are marked implemented and tests prove
  that generated schemas expose neither Settings nor secret-bearing models.
