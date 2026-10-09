# Hiruzen Practice API

Hiruzen is the independently owned practice boundary. TASK-19 provides deterministic
default StudyPlans, a protected four-type Exercise contract, idempotent asynchronous
generation jobs, learner-safe PracticeSet reads and a lease-safe worker port. TASK-20
will connect that worker to Agent evidence retrieval and structured LLM generation.

The architecture and product contracts are maintained in:

- [`docs/function_spec.md`](docs/function_spec.md)
- [`docs/design_spec.md`](docs/design_spec.md)
- [`docs/requirements-traceability.md`](docs/requirements-traceability.md)

## Database and migrations

Hiruzen owns the PostgreSQL `practice` schema and has no foreign keys into Agent tables.
Production should set `PRACTICE_POSTGRES_DSN` to a restricted Practice database role;
when omitted, local development uses `POSTGRES_DSN` on the shared server.

```bash
uv run alembic -c apps/practice/alembic.ini upgrade head
```

## Run and observe the API

```bash
uv run uvicorn course_tutor_practice.app:create_app --factory --port 8001
curl -H "Authorization: Bearer ${COURSE_TUTOR_AUTH_TOKEN}" \
  http://127.0.0.1:8001/v1/practice/capabilities
```

For an Agent-published Book, create/read its default plan and submit an idempotent job:

```bash
curl -H "Authorization: Bearer ${COURSE_TUTOR_AUTH_TOKEN}" \
  "http://127.0.0.1:8001/v1/practice/catalog/books/<BOOK_ID>/study-plan"

curl -X POST \
  -H "Authorization: Bearer ${COURSE_TUTOR_AUTH_TOKEN}" \
  -H 'Idempotency-Key: example-request-1' \
  -H 'Content-Type: application/json' \
  -d '{"count":5,"language":"zh"}' \
  "http://127.0.0.1:8001/v1/practice/catalog/books/<BOOK_ID>/generations"
```

The accepted job is observable through
`GET /v1/practice/generations/{generation_id}`. Until TASK-20 is complete, no real
question generation is attempted; failure/retry remains explicit.

## Verification

```bash
uv run pytest apps/practice/tests tests/integration/practice -q
uv run python scripts/validate_hiruzen_baseline.py
```

Integration tests require the disposable database configured by
`infra/docker/docker-compose.test.yml`; they refuse destructive migration operations
unless the database name starts with `course_tutor_test_`.
