# Release readiness checklist

A release is eligible only when every required item has machine-readable evidence.

- [ ] CI for the exact commit is green, including tests, RAG gates, scans and Kind.
- [ ] Release manifest records chart version, actor and four signed image digests.
- [ ] Environment values reference external secrets and immutable images; production
      has at least two backend replicas, PDB and HPA enabled.
- [ ] Running image IDs equal the release manifest and post-deploy Agent, Practice, Web,
      metrics and RAG smoke checks pass.
- [ ] Current RAG benchmark meets Recall@5, citation precision and abstention thresholds.
- [ ] HA drill loses one backend pod under traffic with zero failed health requests.
- [ ] Worker duplicate-delivery and memory-purge idempotency tests pass.
- [ ] PostgreSQL restore drill meets RPO 24 h/RTO 4 h; current provider evidence exists
      for Qdrant snapshots and object-store version restore.
- [ ] Failed rollout/Helm rollback drill passes and alert routing/runbook links are valid.
- [ ] Memory deletion and content rollback have audit records and operational metrics.
- [ ] Open risks, SLO budget and LM Studio redundancy status are approved by the release
      owner. Production approval is never inferred from a README status.

Run the deterministic local gate with `scripts/release-readiness.sh`. Set
`RUN_CLUSTER_DRILLS=true` only against a disposable non-production namespace. Archive
the JSON reports from `build/reports/` with the immutable release evidence.
