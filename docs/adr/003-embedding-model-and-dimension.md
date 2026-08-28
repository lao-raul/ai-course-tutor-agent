# ADR-003: Embedding model and vector dimension

**Status:** Accepted
**Date:** 2026-08-28
**Deciders:** project owner

## Context

Design-spec §9 listed the loaded LM Studio models as an open question blocking
implementation, because the embedding width fixes the Qdrant collection shape and the
chat model's context window fixes the prompt budget.

The LM Studio host at `http://192.168.50.146:1234/v1` was probed directly.

## Decision

| Setting | Value |
|---|---|
| Chat model | `qwen/qwen3.6-35b-a3b` |
| Embedding model | `text-embedding-qwen3-embedding-0.6b` |
| Embedding dimension | **1024** (measured, not assumed) |

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
- The host also has `openai/gpt-oss-20b`, `zai-org/glm-4.7-flash` and
  `text-embedding-nomic-embed-text-v1.5` loaded. Keeping the model name in configuration
  makes A/B comparison a config change plus a reindex.

## Consequences

- Switching embedding models requires a new Qdrant collection and a full reindex. This is
  intended; it is what keeps versions coherent.
- The chat model's context window is **not yet measured**, so the prompt budget in
  design-spec §5 (rolling summary ≤ 500 tokens, recalled memory ≤ 8 facts / 350 tokens)
  remains provisional. It must be confirmed before Phase 3 tunes memory injection.
- The single LM Studio host remains a single point of failure, as the function spec
  acknowledges. Real HA needs a second compatible node and health-aware routing.

## Follow-up

- Measure the chat model's context window and record it in configuration.
- Benchmark `text-embedding-qwen3-embedding-0.6b` against
  `text-embedding-nomic-embed-text-v1.5` on the Phase 2 retrieval fixture before
  treating the choice as settled.
