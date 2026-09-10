# TASK-08 — Reproducible Container Packaging

**Status:** complete (2026-09-10)
**Priority:** P0
**Depends on:** TASK-02, TASK-03, TASK-04, TASK-07

## Goal

Produce reproducible, minimal and independently deployable images for the two backend apps and supporting workloads.

## Scope

- Build separate images: `agent-api`, `practice-api`, `ingestion-worker` and `web`.
- Use the committed lockfiles with frozen installs; do not regenerate locks during image builds.
- Remove development/test dependencies and compilers from runtime images.
- Run all Python workloads as a non-root user with a read-only root filesystem where practical.
- Add OCI labels for revision, version and source; tag by Git SHA and release version.
- Add multi-platform BuildKit/buildx support and layer caching.
- Add `.dockerignore` coverage for `.env`, NAS data, caches and local artifacts.
- Provide a deterministic fake-LLM image/service used only by CI/Kubernetes smoke tests.
- Align Qdrant client/server supported versions and pin third-party production images instead of `latest`.
- Generate SBOMs and scan images for critical/high vulnerabilities according to an explicit policy.

## Deliverables

- Production Dockerfiles and local Compose wiring for both backend apps.
- Image build matrix/script and documented image names/tags.
- Container-level health checks and smoke tests.

## Acceptance criteria

- Every image builds from a clean checkout with no local `.env` or source documents.
- Runtime images contain no dev toolchain and run as non-root.
- Agent and Practice API images can be started and probed independently.
- A Git SHA can be read from image metadata and `/healthz` build information.
- Vulnerability and secret scans pass the agreed release policy.

## Verification

```bash
docker buildx bake --check
docker buildx bake
docker compose -f infra/docker/docker-compose.yml up --wait
```
