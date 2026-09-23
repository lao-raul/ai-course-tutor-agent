# TASK-17 — Persistent K-12 storage and content-addressed ingestion

**Status:** complete (2026-09-16)
**Priority:** P0
**Depends on:** TASK-03, TASK-09, TASK-12, TASK-16

## Objective

Make the stateful data plane safe and capacity-bounded before the approximately
43 GiB ChinaTextbook working tree is registered. Keep original textbooks and backup
artifacts on NAS while keeping Qdrant active storage on supported block storage.

## Scope

- Add persistent/existing PVC configuration for the built-in PostgreSQL, Qdrant and
  MinIO development dependencies; retain `emptyDir` only as an explicit disposable
  default for CI.
- Keep Qdrant data and snapshot volumes separate. Provide a scheduled collection
  snapshot job so the snapshot PVC can be backed by NAS while the data PVC remains
  SSD/block storage.
- Raise the real-content Qdrant memory budget to 2 GiB requested/4 GiB limited.
- Make source-artifact replication configurable. When enabled, store originals under
  a SHA-256 content-addressed key and skip an object that already exists.
- Reuse unchanged SourceDocument, Chunk and Qdrant points across immutable
  ContentVersions through explicit version/source membership.
- Allow courses to be registered with automatic scans disabled; manual ingestion
  remains available for selected or batched K-12 activation.
- Document capacity, storage placement, backup and operational constraints.

## Acceptance criteria

- A chart render can create dedicated PostgreSQL, Qdrant and MinIO PVCs or reference
  existing claims independently.
- Qdrant active data never needs an NFS/SMB PVC; the separately mounted snapshot claim
  can use NAS and a CronJob creates `course_chunks` snapshots on a configurable schedule.
- Real-content values request at least 2 GiB and cap Qdrant at 4 GiB or more.
- `STORE_SOURCE_ARTIFACTS=false` starts the worker without contacting MinIO.
- Re-uploading the same checksum performs no second object write.
- An unchanged file in a new ContentVersion reuses its SourceDocument and Chunk rows;
  active-version retrieval is scoped by version/source membership and therefore uses
  the same Qdrant point.
- A registered source with `automatic_ingestion_enabled=false` is ignored by the
  scheduler but can still be queued manually.
- Unit, integration, migration, Helm lint/render and contract checks pass.

## Verification

- `uv run pytest tests/unit tests/integration/ingestion tests/unit/test_retrieval_acl.py`
- `uv run alembic -c apps/api/alembic.ini upgrade head`
- `helm lint infra/k8s/course-tutor`
- `helm template course-tutor infra/k8s/course-tutor -f infra/k8s/course-tutor/values-local-real.example.yaml`
- `python scripts/validate_contract_baseline.py`
- `python scripts/validate_delivery.py`

Completion evidence: [`../verification/2026-09-16-task-17.md`](../verification/2026-09-16-task-17.md).

## Rollback

- Disable the snapshot CronJob and return external service URLs to the previous values.
- Existing content-addressed objects are safe to retain because keys are immutable.
- Downgrading the database removes version/source memberships only after a database
  backup; canonical sources must be re-ingested if the downgrade is executed.
