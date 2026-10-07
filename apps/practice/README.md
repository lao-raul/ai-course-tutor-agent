# Practice API

Independently deployable FastAPI boundary for future random exercise generation.
Version 0.1 exposes liveness, readiness and capability discovery, but deliberately
returns `501 practice_generation_not_implemented` from the generation operation.

The accepted target product evolution is named **Hiruzen**. It is specified in:

- [`docs/requirement.md`](docs/requirement.md)
- [`docs/function_spec.md`](docs/function_spec.md)
- [`docs/design_spec.md`](docs/design_spec.md)

TASK-18 has started the Agent-owned Catalog persistence and ChinaTextbook staging
foundation. The user-facing Practice generation API remains the current dummy until
the H1–H3 delivery gates in the design specification are complete.

Run locally:

```bash
uv run uvicorn course_tutor_practice.app:create_app --factory --port 8001
```

Authenticated endpoints use the same `course-tutor-auth` package as Agent API. A
verified `course_ids` claim scopes learners; instructor and platform-admin identities
have tenant-wide course access. The local development identity is a platform admin.
