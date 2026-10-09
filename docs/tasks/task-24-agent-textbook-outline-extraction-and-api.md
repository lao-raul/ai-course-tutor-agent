# TASK-24 — Agent Textbook Outline Extraction and API

**Status:** complete (2026-10-09)
**Priority:** P0
**Depends on:** TASK-15, TASK-18

## Goal

Extract a deterministic, content-versioned textbook outline in Agent and expose it
through an authorized HTTP contract so Hiruzen can build real Chapter/Topic study plans
without importing Agent internals or inventing textbook structure.

## Scope

- Persist an ordered outline for each published Book/ContentVersion.
- Prefer PDF bookmarks, then reliable table-of-contents text and heading rules; use OCR
  only when the document has no reliable text layer.
- Never use unconstrained LLM output as the canonical outline.
- Expose outline availability, confidence, provenance and page anchors through a
  tenant-authorized Agent API.
- Return an explicit unavailable result when confidence is insufficient so Hiruzen can
  apply its one-book-module fallback.
- Validate the first real corpus slice with the primary-school English FLTRP/外研社
  Chen Lin Grade-3-start Grade 3 first-term volume.

## Deliverable artifacts

| Artifact | Repository path |
|---|---|
| Versioned outline DTO and schema | `packages/contracts/src/course_tutor_contracts/catalog_outline.py` |
| Agent outline persistence and migration | `apps/api/src/course_tutor_api/db/`, `apps/api/alembic/versions/*_book_outline.py` |
| Deterministic PDF outline extractor | `services/ingestion/src/course_tutor_ingestion/outline.py` |
| Ingestion lifecycle integration | `services/ingestion/src/course_tutor_ingestion/jobs.py` |
| Authorized Agent outline route | `apps/api/src/course_tutor_api/routes/catalog_outline.py` |
| Versioned Agent OpenAPI update | `packages/contracts/openapi/agent-api.v1.json` |
| Unit and integration tests | `services/ingestion/tests/test_outline.py`, `tests/integration/catalog/test_book_outline.py` |
| Redacted FLTRP outline fixture/manifest | `tests/fixtures/hiruzen/outlines/` |
| Local real-pilot verifier | `scripts/verify_outline_pilot.py` |
| Completion evidence | `docs/verification/<date>-task-24.md` |

## Acceptance criteria

- **AC-24.1:** Reprocessing identical source bytes with the same extractor version
  produces the same ordered node IDs, hierarchy, titles and page anchors.
- **AC-24.2:** Extraction applies the documented priority of PDF bookmarks, reliable
  table-of-contents/heading text and then OCR only when no reliable text layer exists;
  an LLM is never the canonical outline source.
- **AC-24.3:** Every outline is bound to `book_id` and `content_version_id`; the API
  rejects cross-tenant access and never serves stale or unpublished content as current.
- **AC-24.4:** Low-confidence or structurally invalid extraction is represented as
  `UNAVAILABLE` with reason/provenance, and neither Agent nor Hiruzen invents chapters
  or learning objectives.
- **AC-24.5:** Responses and default logs contain no filesystem path, credential or raw
  textbook body text; only bounded titles, hierarchy, page anchors and provenance are
  exposed.
- **AC-24.6:** The redacted FLTRP pilot manifest has an exact automated match for its
  reviewer-approved node order, titles and page anchors, or records an explicit
  reviewer-approved `UNAVAILABLE` outcome.
- **AC-24.7:** Migration round trip, extractor fixtures, authorization/API contract and
  OpenAPI validation tests pass in generated-fixture CI without NAS or LM Studio access.
- **AC-24.8:** Hiruzen's `OutlineProvider` can consume the versioned HTTP DTO and
  distinguish `AVAILABLE` from `UNAVAILABLE` without importing Agent Python modules.

## Independent delivery boundary

TASK-24 owns Agent outline extraction, persistence and the read API only. TASK-19 may
proceed in parallel against a fake `OutlineProvider` and the deterministic book-level
fallback. TASK-24 does not create Hiruzen StudyPlans or generation jobs. Real Chapter/
Topic browser acceptance in TASK-22 requires both TASK-19 and TASK-24.

## Verification

```bash
uv run pytest services/ingestion/tests/test_outline.py tests/integration/catalog/test_book_outline.py -q
uv run alembic -c apps/api/alembic.ini upgrade head
uv run alembic -c apps/api/alembic.ini downgrade base
uv run alembic -c apps/api/alembic.ini upgrade head
uv run alembic -c apps/api/alembic.ini check
uv run python scripts/validate_openapi.py
uv run python scripts/validate_hiruzen_baseline.py
# Optional real-corpus acceptance; never run in CI:
uv run python scripts/verify_outline_pilot.py --pdf "$PILOT_PDF"
```

The dated completion evidence must include the extractor version, redacted source
checksum, extraction provenance, confidence decision and reviewer result for the pilot
volume; it must not contain textbook pages or NAS paths.
