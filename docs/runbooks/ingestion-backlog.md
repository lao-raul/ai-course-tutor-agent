# Ingestion backlog and retrieval regression runbook

1. Inspect pending/dead-letter depth by stable topic and worker logs. Use event IDs or
   correlation IDs; never copy source text into an incident ticket.
2. For `ingestion.scan`, verify the read-only PVC and SourceRoot path. For
   `ingestion.embed`, verify Qdrant and the embedding model/dimension. For
   `memory.purge`, prioritize privacy deletion over new ingestion work.
3. Scale workers only after confirming PostgreSQL/Qdrant/LM Studio capacity. Claims use
   `FOR UPDATE SKIP LOCKED` and idempotency keys, so replicas may process concurrently.
   Also inspect `lastState.terminated.reason`: an `OOMKilled` extraction worker needs a
   larger per-Pod memory limit or smaller source-file batches, not extra replicas. The
   Leeds image-heavy baseline exceeded 2 GiB and completed with a 4 GiB limit.
4. Retry only through the supported admin operation after correcting the cause. Do not
   edit outbox rows or publish a partially built version.
5. If empty-retrieval ratio rises, compare the RAG benchmark, active content version,
   source failures and scope metadata. Roll back the content version when the previous
   published snapshot is safer.
6. Close the incident after the queue is inside the 30-minute freshness objective,
   dead letters are explained, and a cited/abstained chat regression passes.
