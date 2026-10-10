# ADR-006: Hiruzen ownership and Agent integration

- **Status:** Accepted
- **Date:** 2026-10-07
- **Decision owner:** Project owner
- **Amends:** [ADR-004](004-two-backend-apps-and-data-ownership.md)

## Context

The previously reserved Practice API now has a product definition named Hiruzen:
catalog/category search, book-associated courses, grounded exercise generation, inline
and live tutoring, attempts, study status and resume. The textbooks remain part of the
Agent-owned NAS ingestion and RAG system.

Allowing Hiruzen to read Agent tables, NAS or Qdrant would duplicate authorization and
content-version logic. Keeping the substantive service as a permanent sidecar would
also couple its scaling and failures to chat traffic.

## Decision

1. Agent remains authoritative for tenant/course authorization, book catalog metadata,
   NAS ingestion, content versions, deterministic textbook outlines, retrieval evidence
   and grounded live chat.
2. Hiruzen owns StudyPlans, generation jobs, immutable PracticeSets, protected answers,
   attempts, reports, progress and resume cursors.
3. Hiruzen consumes versioned Agent HTTP contracts using workload identity plus the
   delegated user authorization context. It does not import Agent ORM/business modules,
   join Agent tables, access Qdrant or mount NAS.
4. Exercise generation is asynchronous. A Hiruzen worker retrieves bounded evidence
   from Agent, calls an OpenAI-compatible LLM, validates structured output and persists
   an immutable result pinned to Agent content/evidence versions.
5. The Web client calls Agent directly for grounded SSE tutoring chat in assessment
   mode. Hiruzen does not operate a second RAG/chat implementation.
6. Hiruzen data starts in a separately owned PostgreSQL schema/role and may later move
   to a separate server without changing service contracts.
7. Once generation implementation begins, Hiruzen API and worker move to independent
   Deployments within the same Helm release. The dummy two-container backend layout is
   a transition state, not the target production topology.

## Consequences

### Positive

- Textbook ingestion, ACL filtering and citation correctness keep one owner.
- Practice can scale and fail independently from Agent chat.
- Attempts and progress can evolve without changing Agent's content schema.
- Generated sets remain reproducible across content and model changes.

### Costs

- Agent needs versioned catalog, textbook-outline and delegated evidence endpoints.
- Cross-service authentication, timeout, retry and contract testing are required.
- A second schema, migration chain and worker add operational components.
- Catalog availability depends on Agent unless a safe short-lived cache is enabled.

## Alternatives rejected

- **Practice reads Agent PostgreSQL/Qdrant directly:** rejected because it bypasses
  authorization/content-version boundaries and prevents independent evolution.
- **Practice scans ChinaTextbook itself:** rejected because it duplicates ingestion and
  immutable version ownership.
- **Agent generates and stores all exercises:** rejected because attempts/progress are a
  separate bounded context with different scaling and lifecycle needs.
- **Permanent Agent/Practice sidecar:** rejected for the substantive service because
  generation traffic and failures should not scale or roll out with chat.

## Follow-up

- The specialist Function and Design Specifications under `apps/practice/docs/` are
  accepted as the v0.3 baseline.
- Delivery tasks TASK-18 through TASK-24 implement H1–H6 plus the H1a outline slice
  with explicit artifacts, acceptance criteria and independent delivery boundaries.
- TASK-25 separately tracks the privileged H7 instructor preview; it does not expand
  the learner-release deployment boundary of TASK-23.
- Update Agent and Practice OpenAPI contracts before implementing service calls.
