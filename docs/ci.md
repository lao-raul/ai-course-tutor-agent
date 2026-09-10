# Continuous integration

`.github/workflows/ci.yml` is the required pull-request gate. It has six jobs:

1. Python lint, formatting, strict type checking, unit/contract/ACL/SSE tests, JUnit,
   and XML coverage.
2. React unit tests and production build.
3. Disposable PostgreSQL/Redis/Qdrant/MinIO integration tests, the generated-course
   E2E flow, and the machine-readable RAG quality gate.
4. Alembic upgrade → downgrade → upgrade plus model/schema parity.
5. Git-history secret scanning.
6. Frozen image builds, SPDX SBOM, source/image vulnerability scanning, Helm
   validation/package, a clean Kind install, and in-cluster smoke tests.

All third-party Actions are pinned to full commit SHAs. The workflow has read-only
repository permissions, does not push pull-request images, and never references NAS
paths, LAN addresses, or real course content.

## Controlled negative checks

Run these only on a temporary branch; each change must make the corresponding job
fail, and must then be reverted:

- Change the backend readiness path in the chart to `/broken-readyz`; the Kind install
  must fail and Helm must roll back atomically.
- Remove a required `apiVersion` from a template; Helm lint/template must fail.
- Change the expected Alembic revision; backend and worker init containers must not
  admit the rollout.
- Remove the tenant filter in retrieval; the ACL regression suite must fail.
- Change an OpenAPI response shape; the contract baseline test must fail.

The first GitHub-hosted run requires committing and pushing the workflow. This is not
performed by local verification because it changes the remote repository.
