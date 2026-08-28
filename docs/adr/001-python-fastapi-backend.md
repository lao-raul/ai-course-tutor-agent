# ADR-001: Python + FastAPI for the backend

**Status:** Accepted
**Date:** 2026-08-28
**Deciders:** project owner

## Context

The system is a retrieval-augmented teaching assistant. Its hardest work is document
parsing (PDF/PPTX/DOCX/OCR), chunking, embedding, hybrid retrieval, reranking and
prompt orchestration, plus a streaming chat API and background ingestion jobs.

Candidate stacks were Python (FastAPI), TypeScript (NestJS/Fastify) and Go.

## Decision

The backend is **Python 3.12 with FastAPI**, Pydantic v2 for validation, SQLAlchemy 2.0
with Alembic for persistence, and async HTTP clients throughout.

## Rationale

- The document-parsing and RAG evaluation ecosystem is overwhelmingly Python. Parsers
  (Unstructured, pypdf, python-pptx), OCR bindings and retrieval-evaluation tooling are
  first-class there and second-class elsewhere. Ingestion is the largest body of work in
  Phases 1–2, so the ecosystem should favour it.
- FastAPI gives native async streaming (SSE) for token delivery, and Pydantic models
  double as the OpenAPI contract — which the design spec already requires to be
  published from the gateway.
- Pydantic v2 lets the closed memory schema be enforced at the type layer rather than in
  hand-written validation, which is what makes the memory extraction policy
  deterministic.
- One language across gateway, orchestrator, ingestion, retrieval and memory keeps the
  shared `contracts` and `shared` packages usable by every component without a code
  generation step.

## Consequences

- Python's throughput per core is lower than Go's. This is acceptable: the latency
  budget is dominated by LM Studio inference and vector search, not by our own compute.
  Ingestion scales out by worker count, not by single-process speed.
- CPU-bound parsing must run in worker processes, never inline in a request handler,
  or the GIL will stall the event loop serving chat streams.
- Strict typing is not free in Python. `mypy --strict` runs in CI to compensate.
- The web app is TypeScript, so the team carries two languages. The `contracts` package
  is the seam; TypeScript types are generated from the published OpenAPI schema rather
  than hand-maintained.

## Alternatives considered

- **TypeScript end to end** — one language, but every document parser and RAG evaluation
  library would have been a port, a wrapper or a Python sidecar. The sidecar defeats the
  purpose.
- **Go** — best runtime characteristics and easiest deployment, worst ecosystem fit for
  parsing and embeddings. Would have needed a Python service anyway.
