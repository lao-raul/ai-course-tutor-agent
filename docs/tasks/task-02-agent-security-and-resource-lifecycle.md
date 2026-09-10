# TASK-02 — Agent Security and Resource Lifecycle

**Status:** complete (2026-09-09)
**Priority:** P0
**Depends on:** TASK-01

## Goal

Close the current authorization leak and make runtime clients safe under concurrent traffic.

## Scope

- Replace `Depends(get_dependencies)` with a request-only accessor for the lifespan-owned container in `app.state`.
- Ensure Settings never appears in any public OpenAPI request body and cannot be supplied by a caller.
- Stop creating PostgreSQL engines, Redis clients, HTTP clients and Qdrant clients per request.
- Introduce an authentication abstraction with `AUTH_MODE=local` for development/test and OIDC/JWT validation for production.
- Make production reject disabled authentication.
- Derive tenant, user, course membership and access rank from authenticated server-side claims/data.
- Remove `access_label` from student-controlled chat/retrieval request bodies.
- Correct ACL semantics: a user can read only documents whose required rank is less than or equal to their effective rank.
- Scope course listing, course lookup, chat, admin, source and memory operations by tenant and role.
- Protect admin endpoints with instructor/platform-admin authorization.
- Add rate-limit hooks and audit events for administrative and memory-deletion actions.

## Deliverables

- Authentication/authorization dependencies and local test identity provider.
- Correct Qdrant ACL filters applied before candidate retrieval, not only after over-fetch.
- OpenAPI security schemes and documented local-development token flow.
- Unit and integration tests for anonymous, wrong-tenant, public, enrolled, staff and restricted access.

## Acceptance criteria

- An enrolled user cannot retrieve staff-only/restricted chunks even when crafting a raw HTTP request.
- A public user can retrieve public chunks.
- A user from tenant A cannot list or retrieve tenant B courses/content.
- OpenAPI chat request contains only the documented ChatRequest fields and no Settings schema.
- Repeated requests reuse lifespan clients; shutdown closes each client exactly once.

## Verification

```bash
uv run pytest tests/unit tests/integration/security -q
uv run mypy packages apps services
uv run ruff check .
```

## Completion evidence

- `tests/integration/security/test_security_boundary.py` covers anonymous, role, tenant, local identity, OIDC signature/audience validation and OpenAPI privilege-escalation boundaries.
- `tests/unit/test_retrieval_acl.py` covers public/enrolled/staff/restricted rank semantics and verifies tenant/course/version/access prefilters.
- `tests/unit/test_dependency_lifecycle.py` verifies request reuse and one-time client shutdown.
- `uv run pytest tests/unit tests/integration/security -q`, strict mypy and Ruff passed on 2026-09-09.

Memory routes remain intentionally owned by TASK-06; the append-only `AuditEvent` model and tenant/role dependencies introduced here are the mandatory hooks that those routes must use for deletion.
