# TASK-16 — Typed Unit Scope and Summary Retrieval

**Status:** complete (2026-09-13)
**Priority:** P0
**Depends on:** TASK-04, TASK-14

## Goal

Ensure that an explicit request such as `summarize Unit 2` retrieves Unit 2 course
material and never treats the same-numbered Week 2 quiz as an interchangeable scope.

## Problem statement

The original path boost discarded whether a number came from `Unit` or `Week` and
then matched both path forms. It also ran only after dense recall, so the correct
Unit document could not be recovered if it was absent from the initial candidates.
The observed request selected five Week 2 quiz chunks even though
`webinar/unit2/Unit2_slides.pdf` had been indexed into 21 page chunks.

## Scope

- Extract typed canonical scope keys such as `unit:2` and `week:2`.
- Persist those keys in each Qdrant chunk payload and maintain a keyword index.
- Apply an explicit scope as part of the Qdrant filter before dense ranking.
- Keep lexical/path score adjustment type-safe.
- Permit a scoped query to use enough chunks from one source for a multi-page summary.
- Advance the ingestion pipeline identity so existing courses are re-indexed with the
  new payload metadata.
- Add regression coverage for Unit 2 versus Week 2 collisions.

## Acceptance criteria

- `Unit 2` creates a `content_scopes=unit:2` retrieval filter and does not create a
  `week:2` filter or boost.
- `Week 2` remains independently addressable.
- A scoped query cannot silently fall back to a different same-numbered scope.
- Newly indexed `webinar/unit2/...` chunks contain `content_scopes=["unit:2"]`.
- The local real-data request `give a summarize of unit 2` cites only Unit 2 material
  and produces a useful multi-topic summary.
- Retrieval unit tests, lint and type checks pass.

## Verification

```bash
uv run pytest tests/unit/retrieval -q
uv run ruff check apps/api services/retrieval tests/unit/retrieval
uv run mypy apps/api/src services/retrieval/src
```

Runtime verification requires rebuilding the Agent and worker images, upgrading the
Helm release, ingesting/publishing pipeline version `1.4.0`, and repeating the exact
browser/API query against the NAS-backed course.

## Completion evidence

- Typed scope extraction preserves `unit:2` and `week:2` as different keys and the
  Qdrant query applies the key before vector recall.
- The ingestion indexer writes `content_scopes` and collection maintenance adds the
  keyword payload index to both new and existing collections.
- Pipeline version `1.4.0` forced an immutable real-course re-index; the resulting
  version was published locally.
- The exact reported query produced 20 candidates, all from
  `webinar/unit2/Unit2_slides.pdf`; no Week 2 quiz entered the candidate set.
- The generated summary cited Unit 2 pages 1, 3, 5, 15 and 21 and covered matrix
  structure, eigenstructure, SVD, numerical reliability and machine-learning links.
- Helm revision 6 deployed the corrected Agent and Worker images successfully.
- All 89 unit tests, targeted integration coverage, Ruff and mypy passed. The
  NAS/LM Studio E2E also passed grounded streaming, citation validation and unrelated
  question abstention.
