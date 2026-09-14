# ADR-003: Embedding model and vector dimension

**Status:** Accepted
**Date:** 2026-08-28
**Deciders:** project owner

## Context

Design-spec §9 listed the loaded LM Studio models as an open question blocking
implementation, because the embedding width fixes the Qdrant collection shape and the
chat model's context window fixes the prompt budget.

The configured LM Studio host was probed directly; its private endpoint is kept in
untracked local configuration.

## Decision

| Setting | Value |
|---|---|
| Chat model | `qwen/qwen3.6-35b-a3b` |
| Embedding model | `text-embedding-qwen3-embedding-0.6b` |
| Embedding dimension | **1024** (measured, not assumed) |
| Chat context window | **262144** tokens (verified against the live host) |

`LLM_EMBEDDING_DIMENSION` is configuration, and `LMStudioProvider.embed()` **fails
closed** when the provider returns a different width.

Qdrant uses **one collection per embedding model and version**. Changing the embedding
model is therefore a new collection plus a reindex, never an in-place mutation.

## Rationale

- A dimension mismatch does not raise naturally: vectors of the wrong width either get
  rejected deep inside Qdrant or, worse, produce an index whose similarity scores are
  meaningless. Asserting the width at the provider boundary turns a silent quality
  failure into a startup-time error (function-spec §7.4).
- Recording the dimension on `content_versions` means a published version carries the
  embedding contract it was built under, so a model change cannot make an existing
  version quietly unsearchable.
- Keeping model names in configuration makes A/B comparison a config change plus a
  reindex without recording the host's full private model inventory.

## Consequences

- Switching embedding models requires a new Qdrant collection and a full reindex. This is
  intended; it is what keeps versions coherent.
- Prompt budgets remain deliberately smaller than the verified context window so
  retrieval evidence, conversation state and generation headroom stay bounded.
- The single LM Studio host remains a single point of failure, as the function spec
  acknowledges. Real HA needs a second compatible node and health-aware routing.

## Follow-up

- ~~Measure the chat model's context window and record it in configuration.~~ **Resolved** — 262144 tokens.
- Benchmark `text-embedding-qwen3-embedding-0.6b` against
  `text-embedding-nomic-embed-text-v1.5` on the Phase 2 retrieval fixture before
  treating the choice as settled.
