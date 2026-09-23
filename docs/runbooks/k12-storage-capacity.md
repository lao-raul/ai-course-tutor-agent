# K-12 storage capacity and placement

## Measured corpus baseline

The NAS source `/volume1/homes/lvjial/ChinaTextbook` was measured on 2026-09-16:

- 85 GiB checkout total, including approximately 42 GiB of `.git` history.
- Approximately 43 GiB working tree: 1,905 complete PDFs (29.7 GiB) and 466 split
  parts belonging to 182 additional PDFs (13.7 GiB).
- A 47-file sample averaged 86.6 pages, projecting roughly 180,000 pages after split
  PDFs are reconstructed.

The hidden `.git` directory is pruned by the scanner and is not indexed.

## Placement

| Data | Required placement | Reason |
|---|---|---|
| ChinaTextbook originals | NAS, read-only PVC | Existing source of record; sequential ingestion reads |
| PostgreSQL active data | Local SSD/block PVC or PostgreSQL running directly on NAS-local storage | Transactional durability and predictable `fsync` |
| Qdrant active data | SSD/NVMe or CSI/iSCSI block PVC | Qdrant does not support NFS/SMB active storage |
| Qdrant snapshots | Separate NAS-backed PVC | Sequential backup/restore artifact, not live segments |
| MinIO artifacts | External NAS/object service, or disabled for immutable NAS originals | Avoid duplicate 43 GiB source copies |
| Redis | Disposable or managed | Cache/session acceleration; not the durable system of record |

Never mount an SMB share directly as PostgreSQL `PGDATA` or `/qdrant/storage`.
Running PostgreSQL on the NAS itself is acceptable for a home-lab deployment when the
database process uses a NAS-local volume, the NAS has a UPS, and backups are tested.

## Capacity envelope

At 200,000–500,000 chunks and 1024-dimensional Float32 embeddings, raw dense vectors
occupy approximately 0.8–2.0 GiB. Payload, HNSW, WAL and optimizer headroom put a
single active Qdrant copy in the approximate 3–10 GiB range. PostgreSQL text and
metadata are expected to consume 2–8 GiB. Measure a representative set before final
allocation.

Recommended free capacity:

- Development, one replica: 100–150 GiB.
- Sources plus snapshots/backups: 200–300 GiB.
- Replicated production data plane: at least 300 GiB, then size from observed metrics.

## Staged ingestion

1. Register K-12 courses with `automatic_ingestion_enabled: false`.
2. Ingest and evaluate one representative textbook per education level.
3. Publish only versions that pass extraction and RAG gates.
4. Queue remaining courses in bounded batches through the manual ingestion endpoint.
5. Enable automatic scans only for courses that should track NAS changes.

For immutable NAS sources, set `config.storeSourceArtifacts: false`. If artifact
replication is required, leave it enabled; SHA-256 keys ensure one object per unique
file regardless of version count.

## Qdrant snapshots

Set `internalDependencies.qdrant.snapshots.enabled: true` and point
`existingClaim` at a NAS-backed PVC. The chart CronJob calls the collection snapshot
API on the configured schedule. Keep `internalDependencies.qdrant.persistence` on a
different block-backed PVC. Periodically restore a snapshot into a disposable Qdrant
instance and record the result in the release evidence.
