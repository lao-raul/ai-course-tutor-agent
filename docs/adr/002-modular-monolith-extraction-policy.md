# ADR-002: Modular monolith first, with an explicit extraction policy

**Status:** Accepted
**Date:** 2026-08-28
**Deciders:** project owner

## Context

The function spec describes seven deployable services (web, gateway, orchestrator,
ingestion, retrieval, memory, model gateway). The initial deployment is a single local
Docker Compose stack serving one course for a small number of users.

Building seven independently deployed services now would mean seven pipelines, seven
health surfaces and distributed tracing across process boundaries — before a single
grounded answer has been produced.

## Decision

Deploy as **one modular monolith** built from **separately packaged modules**, and treat
service extraction as a later, cheap operation rather than an upfront cost.

Three rules make extraction cheap:

1. **Contracts are explicit and shared.** All cross-module shapes live in
   `packages/contracts` as versioned Pydantic DTOs. Modules never reach into each
   other's ORM models.
2. **Modules do not import each other's internals.** `packages/shared` holds only
   cross-cutting concerns (config, logging, correlation IDs, tracing) and imports no
   service or app module. Dependencies point inward, never sideways.
3. **Asynchronous work already goes through the outbox.** Ingestion, summarisation,
   deletion and reindex jobs are published as `outbox_events` rows with an idempotency
   key, not as in-process function calls. Extraction swaps the consumer's transport
   without touching the producer.

## Extraction triggers

Extract a module into its own service when **any** of these becomes true — not on
architectural preference:

- **Load isolation:** the module's resource profile starves the others. Ingestion is the
  expected first case, since parsing and OCR are CPU-bound while chat is I/O-bound.
- **Release cadence:** the module needs to ship on a materially different schedule.
- **Failure isolation:** a fault in the module takes down unrelated user journeys.
- **Scaling shape:** the module needs a different replica count or hardware class — for
  example, retrieval scaling with vector-search load, or the model gateway needing to
  sit next to a specific inference node.

The model gateway is the likely second extraction, since routing across multiple local
inference nodes (function-spec §7.6) is easier as a standalone hop.

## Consequences

- Phase 0–3 velocity is higher: one process to run, one log stream, in-process calls are
  debuggable with a stack trace.
- The discipline is load-bearing and easy to erode. A cross-module import of an ORM model
  is the failure mode to watch for; it should be caught in review.
- Everything is deployed together until extraction, so a bad release affects all
  modules. Mitigated by the test suite being a merge gate.
- Contract-shaped calls cost a little ceremony now in exchange for not needing a
  rewrite later.

## Alternatives considered

- **Microservices from day one** — correct end state, wrong starting point. It front-loads
  operational work that buys nothing at one course and a handful of users.
- **Unstructured monolith** — fastest short-term, but with no contract boundaries the
  extraction later becomes a rewrite. The spec explicitly wants the migration path kept
  open.
