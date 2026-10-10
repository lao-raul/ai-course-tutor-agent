# Hiruzen Practice API

Hiruzen is the independently owned practice boundary. TASK-19 provides deterministic
default StudyPlans, a protected four-type Exercise contract, idempotent asynchronous
generation jobs, learner-safe PracticeSet reads and a lease-safe worker port. TASK-20
connects that worker to Agent's version-pinned evidence API and structured LLM
generation with validation. TASK-21 and TASK-22 will add attempts/progress and the UI;
TASK-23 will deploy the independent Practice worker through Helm.

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

The Practice and Agent processes must share the same
`PRACTICE_DELEGATION_SECRET` (at least 24 characters; non-placeholder in production).
The Agent API must be reachable at `AGENT_BASE_URL`, and the worker needs the
configured OpenAI-compatible `LLM_BASE_URL` and `LLM_CHAT_MODEL`.

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
`GET /v1/practice/generations/{generation_id}`. With the Practice migration applied
and Agent/LLM dependencies configured, a separate worker process runs the job:

```bash
uv run python -m course_tutor_practice_worker
```

The current Helm chart does not yet include the independent Practice migration and
worker workloads; deployment of those processes is part of TASK-23. The current
browser UI also does not yet expose the Hiruzen generation flow.

## Verification

```bash
uv run pytest apps/practice/tests tests/unit/practice tests/integration/practice tests/e2e/practice -q
uv run python tests/evaluation/hiruzen/run.py --provider fake
uv run python scripts/validate_hiruzen_baseline.py
```

Integration tests require the disposable database configured by
`infra/docker/docker-compose.test.yml`; they refuse destructive migration operations
unless the database name starts with `course_tutor_test_`.
