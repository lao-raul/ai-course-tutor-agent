# TASK-04 — RAG Correctness, Citations and Streaming

**Status:** complete (2026-09-10)
**Priority:** P0
**Depends on:** TASK-02, TASK-03

## Goal

Turn the current RAG demo into a grounded answer path whose access filtering, abstention, citations and streaming behavior are testable and correct.

## Scope

- Build Source numbering and citation lookup from the final evidence list after reranking.
- Validate both source number and chunk ID before emitting a citation; reject unknown or mismatched citations.
- Stream safe answer tokens as they arrive instead of buffering the complete LM Studio response.
- Update the React UI incrementally during token events and retain the completed message afterward.
- Define a deterministic buffering strategy so the hidden citation trailer is never shown to the user.
- Apply a calibrated relevance/groundedness threshold and abstain on low evidence, not merely an empty result set.
- Record the full retrieval candidate list, final reranked list and real component timings before/independently of client disconnect.
- Replace the “hybrid” label unless true lexical/BM25 or sparse retrieval is implemented. Preferred target: dense + lexical recall with reciprocal-rank fusion and a version-compatible Qdrant/client combination.
- Implement a real reranker adapter or document score+diversity ordering as a baseline rather than a cross-encoder reranker.
- Enforce evidence token budgets and source diversity.
- Add provider retry/circuit-breaker behavior for bounded transient failures.

## Deliverables

- Corrected retrieval, evidence, prompt, citation and SSE code.
- Frontend incremental rendering and disconnect/error handling.
- Contract tests for the event stream.
- ADR/update describing the selected lexical and reranking implementation.

## Acceptance criteria

- Reordering candidates cannot change a Source number’s underlying chunk.
- Every emitted citation belongs to the exact evidence pack sent to the LLM.
- The first token reaches a test client before the fake provider completes its response.
- Low-score unrelated queries abstain.
- Retrieval applies tenant/course/version/ACL filters before returning candidates.
- Client cancellation does not leak resources and leaves a valid trace status.

## Verification

```bash
uv run pytest tests/unit/retrieval tests/integration/chat -q
npm --prefix apps/web test
npm --prefix apps/web run build
```

## Completion evidence

- `tests/unit/retrieval/test_grounded_stream.py` proves final-evidence source numbering,
  source+chunk UUID validation, low-score abstention, prompt budgets, split-trailer
  hiding, first-token streaming and cancellation terminal state.
- `tests/integration/chat/test_sse_contract.py` verifies token → citation → done ordering
  through the FastAPI route and confirms the control trailer is not exposed.
- `apps/web/src/api.test.ts` verifies incremental SSE dispatch and abort handling; the UI
  now updates one persistent assistant message as tokens arrive.
- ADR-005 records the accurately named dense+lexical-rescore and score-diversity
  baseline. Provider retries are bounded and a circuit breaker prevents repeated calls
  to an unhealthy LM Studio endpoint.
