# TASK-03 existing-course migration

Revision `8d90c87b7341` is an in-place, data-preserving migration.

- Each tenant that already owns a course receives one `legacy` programme.
- Each existing course is assigned to that programme and receives one `legacy` course run.
- Existing `source_root_id` and `active_content_version_id` aliases are copied to the course run.
- Existing content versions are assigned to the corresponding course run.
- A course without a source root receives an inert `/unconfigured/{course_id}` placeholder. An instructor must register a valid mounted source before ingestion.
- Existing source documents, chunks, Qdrant point IDs and active course aliases are not rewritten.

After deployment, the first scan under pipeline `1.2.0` intentionally builds a fresh immutable version because older versions have no source snapshot hash. Publish it only after preview; the previous published version remains available for rollback.

Run before starting API/worker replicas:

```bash
uv run alembic -c apps/api/alembic.ini upgrade head
uv run alembic -c apps/api/alembic.ini check
```
