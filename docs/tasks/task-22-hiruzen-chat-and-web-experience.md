# TASK-22 — Hiruzen Chat and Web Experience

**Status:** planned  
**Priority:** P1  
**Depends on:** TASK-18–TASK-21

## Goal

Deliver the Hiruzen learner experience for catalog discovery, practice, inline help,
live tutoring, progress and resume.

## Scope

- Add category/book search, book detail and StudyPlan screens.
- Add generation status, exercise answering, hint/give-up and feedback experiences.
- Call Agent SSE chat directly with assessment mode and current attempt context.
- Add Chinese/English/bilingual selection with Chinese default.
- Add accessible loading, error, citation and AI-guidance states.

## Deliverable artifacts

| Artifact | Repository path |
|---|---|
| Typed Hiruzen API client | `apps/web/src/api/practice.ts` |
| Catalog/book/StudyPlan screens | `apps/web/src/features/catalog/` |
| Generation and exercise workflow | `apps/web/src/features/practice/` |
| Progress/resume experience | `apps/web/src/features/study/` |
| Direct Agent SSE inline/live chat adapter | `apps/web/src/features/tutor/` |
| Language and accessibility UI resources | `apps/web/src/features/settings/`, `apps/web/src/i18n/` |
| Component and browser E2E tests | `apps/web/src/**/*.test.tsx`, `tests/e2e/hiruzen/` |
| UX verification evidence | `docs/verification/<date>-task-22.md` |

## Acceptance criteria

- **AC-22.1:** A learner can complete catalog → generate → answer → help → resume
  through the browser without using admin endpoints.
- **AC-22.2:** Inline/live help calls Agent SSE directly, respects answer-release policy
  and cites the published textbook version.
- **AC-22.3:** Reloading or changing devices resumes the latest safe exercise without
  exposing protected answer state.
- **AC-22.4:** Chinese, English and bilingual selection persists for the learner, and a
  new user receives Chinese by default.
- **AC-22.5:** Keyboard navigation, loading/error semantics, AI guidance labels and
  citation rendering pass component and browser accessibility checks.

## Independent delivery boundary

TASK-22 owns Web code only. It may start against generated OpenAPI mocks after TASK-19
contracts freeze; final acceptance waits for TASK-18–TASK-21 implementations.

## Verification

```bash
npm --prefix apps/web test
npm --prefix apps/web run build
uv run pytest tests/e2e/hiruzen -q
```

The completion evidence includes a manual keyboard/accessibility and bilingual UX review.
