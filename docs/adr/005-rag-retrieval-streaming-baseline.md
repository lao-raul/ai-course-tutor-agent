# ADR-005: RAG Retrieval and Streaming Baseline

- **Status:** Accepted
- **Date:** 2026-09-10

## Context

The prototype called its retrieval path hybrid even though lexical terms could only
reorder results already recalled by dense vector search. It also buffered the full
model response before emitting SSE, and built citation numbers from a different list
than the evidence sent to the model.

## Decision

1. Name the v0.2 implementation **dense retrieval with lexical rescoring**. It is not
   true lexical+dense hybrid recall; TASK-05 will evaluate whether a separate lexical
   candidate source and rank fusion are required to meet the quality gate.
2. Use deterministic score ordering with at most two chunks per source as the baseline
   reranker. Select at most five evidence chunks and 3,500 estimated tokens.
3. Abstain when no final candidate reaches the synthetic-benchmark-calibrated baseline
   score of 0.20. TASK-05 records the benchmark metrics and keeps this threshold
   regression-tested.
4. Assign source numbers only after evidence selection. A citation is emitted only
   when both its source number and chunk UUID match that evidence entry.
5. Stream provider chunks immediately while holding only the suffix needed to detect
   a split `CITATIONS:` control marker. The control trailer is never user-visible.
6. Persist retrieval candidates, final evidence, scores, component timings, policy and
   model versions before streaming. Update terminal state using an independent database
   session so disconnect handling does not depend on the request session.
7. Retry inference failures only within bounded attempts. Chat generation can retry
   before its first token but never after visible output begins; repeated failures open
   a circuit breaker.

## Consequences

The current implementation is named honestly and has deterministic correctness tests.
True lexical recall remains a measured quality decision rather than an unsupported
architecture claim. The parser delays at most the short control-marker prefix while
otherwise preserving real token arrival.
