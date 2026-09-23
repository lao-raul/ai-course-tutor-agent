# Backup and restore runbook

## Targets and ownership

- PostgreSQL is canonical: encrypted daily full backup plus continuous WAL archive,
  RPO 24 hours and RTO 4 hours for v0.2.
- Qdrant is a rebuildable projection: snapshot after a published content version and
  before upgrades; otherwise recreate collections by re-running ingestion.
- Object storage keeps immutable source/extraction artifacts: enable bucket versioning
  and replicate encrypted objects according to institutional retention policy.
- Redis is ephemeral and is not restored.

Provider-native backup jobs, retention locks, encryption keys and PITR destinations
must be configured outside this repository. Backups are not successful until a restore
in an isolated namespace is verified.

## Restore order

1. Freeze ingestion and record the last known release/content versions.
2. Restore PostgreSQL to a new instance at the selected point in time and run schema
   compatibility checks without applying a newer migration automatically.
3. Restore the matching object-store version. Restore Qdrant snapshots when available;
   otherwise rebuild it from the restored PostgreSQL/artifacts.
4. Deploy the matching immutable image digests/chart, verify counts and tenant ACLs,
   then run Agent, Practice and RAG smoke tests before switching traffic.
5. Record backup timestamp, achieved RPO/RTO, checksums, actor and verification result.

The internal-dependency non-production drill validates a destructive PostgreSQL
dump/drop/restore round trip and refuses production:

```bash
CONFIRM_NON_PRODUCTION=yes scripts/restore-drill.sh
```

Qdrant/object-store restore uses provider-specific APIs; their quarterly evidence must
be attached to the release checklist. A PostgreSQL-only pass cannot certify those
external systems.

For the built-in local-real dependency, configure a block-backed Qdrant data PVC and
a separate NAS-backed snapshot PVC. Enabling
`internalDependencies.qdrant.snapshots.enabled` creates the scheduled collection
snapshot CronJob. Do not use NFS/SMB for `/qdrant/storage`; see
`docs/runbooks/k12-storage-capacity.md`.
