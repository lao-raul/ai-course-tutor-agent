# TASK-18 — Hiruzen Catalog Contract and ChinaTextbook Import

**Status:** in progress (started 2026-10-07)  
**Priority:** P0  
**Depends on:** TASK-17

## Goal

Create the Agent-owned catalog used by Hiruzen and stage ChinaTextbook metadata from
the read-only NAS without exposing filesystem paths or creating a second RAG/content
owner in the Practice service.

## Scope

- Add tenant-scoped Category, Publisher, Book and book/content/course binding models.
- Add immutable catalog import batches and reviewable candidates.
- Scan ChinaTextbook PDF metadata from configurable read-only roots, initially the
  primary-school English FLTRP family.
- Parse education level, subject, series, publisher, start grade, editor, grade and
  term while quarantining ambiguous layouts.
- Generate stable identity from normalized metadata rather than absolute mount paths.
- Add approval/import workflow and Agent catalog read contracts.
- On approval, create one Book and system-managed Course/CourseRun, then queue existing
  ingestion; publish visibility still requires explicit ContentVersion publication.
- Add server-derived `tenant_authenticated` authorization for published system textbook
  CourseRuns without weakening membership ACLs on normal courses.
- Implement the Hiruzen catalog facade strictly through the Agent HTTP contract.

## Deliverable artifacts

| Artifact | Repository path | Status |
|---|---|---|
| Catalog DTOs and closed enums | `packages/contracts/src/course_tutor_contracts/{domain,enums}.py` | partial |
| Agent Catalog ORM model | `apps/api/src/course_tutor_api/db/models.py` | partial |
| Catalog database migration | `apps/api/alembic/versions/b6a4d2c8e901_hiruzen_catalog_staging.py` | partial |
| ChinaTextbook scanner/staging importer | `services/ingestion/src/course_tutor_ingestion/china_textbook_catalog.py` | implemented |
| Agent catalog admin/read routes | `apps/api/src/course_tutor_api/routes/{catalog_admin,catalog}.py` | remaining |
| Hiruzen Agent client and catalog facade | `apps/practice/src/course_tutor_practice/{adapters/agent_client.py,routes/catalog.py}` | remaining |
| Versioned Agent/Practice contracts | `packages/contracts/openapi/{agent-api,practice-api}.v1.json` | remaining |
| Parser/importer and API contract tests | `tests/{unit/ingestion,integration/catalog}/`, `apps/practice/tests/` | partial |
| Completion evidence | `docs/verification/<date>-task-18.md` | remaining |

## Acceptance criteria

- **AC-18.1:** Re-scanning an unchanged selection produces the same snapshot and no duplicate
  import batch.
- **AC-18.2:** All 36 observed FLTRP pilot PDFs are parsed into reviewable candidates without an
  absolute NAS path in any public response.
- **AC-18.3:** Ambiguous metadata remains `needs_review` and cannot become searchable implicitly.
- **AC-18.4:** Published catalog queries are tenant/authorization scoped and support the filters in
  HFR-CAT-2 with deterministic pagination.
- **AC-18.5:** Hiruzen has no NAS mount and imports no Agent ORM or route module.
- **AC-18.6:** Migration upgrade/downgrade, parser/importer tests, API contract tests and
  baseline validators pass.
- **AC-18.7:** Approved candidates create idempotent Book/CourseRun bindings and queue
  ingestion, while only an explicitly published ContentVersion makes the Book searchable.
- **AC-18.8:** Any authenticated user in the tenant can access a published system
  textbook CourseRun, while cross-tenant and non-system course access still fails closed.

## Independent delivery boundary

TASK-18 owns Agent catalog/import contracts and only the Hiruzen catalog facade. It
must not add Practice persistence or generation behavior. Its versioned Book/CourseRun
DTOs are the frozen input contract for TASK-19 and TASK-20.

## Verification

```bash
uv run pytest tests/unit/ingestion/test_china_textbook_catalog.py tests/unit/test_contracts.py -q
uv run python scripts/validate_hiruzen_baseline.py
uv run ruff check apps/api services/ingestion packages/contracts tests
uv run mypy apps/api/src services/ingestion/src packages/contracts/src
```

## Progress

- Product decisions, corpus inventory and ownership boundary accepted.
- Catalog persistence model/migration foundation, scanner and staging importer are the
  first implementation increment. The scanner/importer is implemented; activation,
  tenant-authenticated CourseRun access and publication fields remain.
- A read-only real-NAS scan found exactly 36 FLTRP pilot PDFs across the four expected
  series with zero parser review issues; snapshot prefix `76c4ca4eb0616d04`.
- Unit tests, Ruff, mypy and both specification baseline validators pass.
- Approval API, public Agent catalog reads and Hiruzen facade remain before completion.
