# TASK-03 — Ingestion and Content-Version Lifecycle

**Status:** complete (2026-09-09)
**Priority:** P0
**Depends on:** TASK-01

## Goal

Support the user’s recurring workflow: files are added or changed on the mounted NAS and become searchable through a safe, versioned ingestion process.

## Scope

- Separate tenant/course/source-root registration from `POST .../ingestions` for an existing course.
- Use one pipeline-version source of truth shared by admin, scanner, embedder and stored content versions.
- Implement periodic scans plus manual trigger; do not rely on SMB filesystem notifications.
- Compare a new snapshot against the current published version and handle add, change, delete and rename deterministically.
- Build a new immutable content version; unchanged documents may reuse extraction/embedding artifacts without sharing mutable rows.
- Move version status through `BUILDING → READY → PUBLISHED` or `FAILED`; embedding completion must set READY transactionally.
- Make publication an explicit alias swap; retain a valid previous published version for rollback.
- Preserve chunk classes during coalescing, calculate real token counts and retain accurate page/slide anchors.
- Fix MinIO bucket creation/configuration and write canonical tenant/course/source IDs instead of placeholders.
- Claim outbox work with database locking (`FOR UPDATE SKIP LOCKED`) or an equivalent lease; support multiple workers safely.
- Ensure path-validation failures increment attempts and eventually dead-letter rather than retry forever.
- Add source/error/status/list/retry APIs needed by the instructor UI.

## Deliverables

- New versioned ingestion API and migrations if needed.
- Scheduler/worker implementation with idempotent scan and embed consumers.
- MinIO initialization and artifact retrieval test.
- Migration path for the existing published course/index.

## Acceptance criteria

- Adding, editing, deleting and renaming a fixture file each creates the expected next version without corrupting the active version.
- Running the same scan/event twice produces no duplicate source, chunk, artifact or vector.
- Two workers processing the same queue do not process one event concurrently.
- A successfully embedded version becomes READY and can be published through the API.
- Failed extraction/embedding is visible, retryable and dead-lettered after the configured limit.
- Exercise/solution/assessment chunk classes survive parsing and coalescing.

## Verification

```bash
uv run pytest tests/unit/ingestion tests/integration/ingestion -q
uv run alembic -c apps/api/alembic.ini upgrade head
uv run alembic -c apps/api/alembic.ini check
```

## Completion evidence

- `tests/integration/ingestion/test_version_lifecycle.py` covers registration separation, add/edit/delete/rename snapshots, immutable sequences, duplicate delivery, READY/publish alias behavior, validation dead-lettering and concurrent worker exclusion.
- `tests/unit/ingestion/` covers semantic chunk classes/anchors/token counts, canonical MinIO artifact round-trip and generated `FOR UPDATE SKIP LOCKED` SQL.
- Revision `8d90c87b7341` upgraded a dedicated PostgreSQL 16 test database and `alembic check` reported no schema drift on 2026-09-09.
- Existing-data mapping and first-rebuild behavior are documented in `docs/migrations/task-03-existing-course.md`.
