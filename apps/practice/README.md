# Practice API

Independently deployable FastAPI boundary for future random exercise generation.
Version 0.1 exposes liveness, readiness and capability discovery, but deliberately
returns `501 practice_generation_not_implemented` from the generation operation.

Run locally:

```bash
uv run uvicorn course_tutor_practice.app:create_app --factory --port 8001
```

Authenticated endpoints use the same `course-tutor-auth` package as Agent API. A
verified `course_ids` claim scopes learners; instructor and platform-admin identities
have tenant-wide course access. The local development identity is a platform admin.
