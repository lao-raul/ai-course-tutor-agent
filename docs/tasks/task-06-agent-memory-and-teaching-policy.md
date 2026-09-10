# TASK-06 — Agent Memory and Teaching Policy

**Status:** ready
**Priority:** P1
**Depends on:** TASK-02, TASK-04

## Goal

Implement useful multi-turn tutoring memory while keeping long-term memory compact, explainable, course-scoped and deletable.

## Scope

- Persist chat sessions and turns; validate that session user/course scope matches the authenticated request.
- Maintain a bounded recent-turn window and rolling summary with deterministic token budgets.
- Extract typed memory candidates through a strict JSON schema only after configured meaningful-turn triggers.
- Reject sensitive, unsupported, low-confidence or unscoped candidates.
- Normalize and deduplicate by deterministic key, then semantic similarity; merge evidence instead of duplicating facts.
- Handle conflicts, supersession, confidence decay, expiry and pinned facts.
- Rank recalled facts by course scope, relevance, importance, freshness and confidence; cap count/tokens.
- Implement inspect, correct, pin, export and tombstone/delete APIs plus derived-data purge jobs.
- Define configurable teaching policies for education level, explanation style and assessed-work hint progression.
- Preserve and enforce exercise/solution/assessment chunk classes from TASK-03.
- Add bilingual Chinese/English behavior tests.

## Deliverables

- `services/memory` implementation and integration with the Agent API/orchestrator.
- Session/turn migrations and APIs.
- Memory management UI and teaching-policy configuration.
- Privacy, deletion and memory-quality tests.

## Acceptance criteria

- Repeating the same preference creates one canonical fact with merged provenance.
- Corrected, expired or tombstoned facts are not recalled.
- Raw transcripts are not used as the sole long-term representation.
- Rolling summary is at most 500 tokens; recalled long-term memory is at most 8 facts/350 tokens unless v0.2 changes these values.
- A configured assessment returns hints according to policy and does not expose a stored solution prematurely.
- The user can inspect why a memory exists and delete it completely.

## Verification

```bash
uv run pytest tests/unit/memory tests/integration/memory tests/e2e/teaching -q
```
