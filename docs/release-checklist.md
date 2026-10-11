# Release readiness checklist

A release is eligible only when every required item has machine-readable evidence.

TASK-23 remediation and review evidence are maintained in the
[unified record](verification/2026-10-10-task-23.md); deferred quality work is
tracked in [Known Issue KI-001](known-issues.md). Neither replaces this checklist.

- [ ] CI for the exact commit is green, including tests, RAG gates, scans and Kind.
- [ ] Release manifest records chart version, actor and five signed image digests
      (Agent API, Practice API, Practice Worker, ingestion worker, Web).
- [ ] Environment values reference external secrets and immutable images; production
      has at least two backend replicas, PDB and HPA enabled.
- [ ] Running image IDs equal the release manifest and post-deploy Agent, Practice, Web,
      metrics and RAG smoke checks pass.
- [ ] Practice migration reaches `p220001` before API/worker readiness; independent
      Practice pods have no `course-content` volume and their HPA/PDB/policies render.
- [ ] The selected FLTRP Chen Lin Grade 3 first-term real-pilot report contains at
      least 20 human-reviewed cases, named dated approval, latency samples and
      HNFR-5–11 operational evidence; `golden_gate.py` passes. A synthetic CI report
      cannot satisfy this production gate.
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
