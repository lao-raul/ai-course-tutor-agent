# TASK-15 — Rich Math Output and PDF Text Quality

**Status:** complete (2026-09-13)
**Priority:** P1
**Depends on:** TASK-03, TASK-04, TASK-14

## Goal

Render tutor answers containing Markdown and TeX as readable, safe course content and
improve the provenance quality of text extracted from mathematical PDF/PPT material.

## Scope

- Define the visible LLM answer contract as GitHub-flavored Markdown with `$...$`
  inline mathematics and `$$...$$` display mathematics.
- Render Markdown and TeX in the React UI with KaTeX while keeping model-authored raw
  HTML disabled.
- Increase KaTeX array spacing for matrices containing stacked fractions and allow
  wide display equations to scroll without overflowing the chat message.
- Preserve incremental SSE behavior: partial Markdown may rerender while streaming,
  and the completed response must render deterministically.
- Apply conservative Unicode normalization to PDF and OCR text, removing invalid and
  invisible control characters without deleting legitimate non-Latin course content.
- Keep PDF pages and presentation slides as independent citation units so chunk
  overlap cannot produce ambiguous anchors such as `page 1-4-5-8`.
- Document that diagrams, image-only formulas and custom-font glyph recovery require
  a separate multimodal extraction enhancement; do not claim that text normalization
  provides visual understanding.

## Deliverables

- Safe Markdown/GFM/KaTeX response component and UI integration.
- Prompt-level visible output format contract.
- PDF/OCR Unicode normalization and page/slide-aware chunking.
- Frontend and backend regression tests.

## Acceptance criteria

- `**Row View**`, lists and `$A$` render as styled content instead of literal syntax.
- Fraction-heavy matrices render with separated rows instead of overlapping glyphs.
- Model-authored `<script>` or other raw HTML is not rendered.
- Prompt instructions and UI agree on Markdown and TeX delimiters.
- Compatibility math characters are normalized and invisible/control characters do
  not enter newly ingested chunks.
- Two adjacent PDF pages or PPT slides produce distinct citation anchors.
- Existing SSE, ingestion, retrieval and frontend tests remain green.

## Verification

```bash
npm --prefix apps/web test
npm --prefix apps/web run lint
npm --prefix apps/web run build
uv run pytest tests/unit/ingestion tests/unit/retrieval -q
uv run ruff check apps/api services/ingestion tests/unit
uv run mypy apps/api/src services/ingestion/src
```

Changing extraction or chunk boundaries requires a new ingestion content version
before an already indexed course benefits from those backend improvements. The Web UI
rendering fix only requires rebuilding and redeploying the Web image.

## Completion evidence

- `apps/web/src/RichText.tsx` renders GFM and TeX through KaTeX with raw HTML disabled.
- `apps/web/src/RichText.test.tsx` verifies bold text, lists, inline mathematics and
  rejection of event-handler-bearing raw HTML.
- The chat prompt now declares the same Markdown/TeX contract consumed by the Web UI.
- PDF/OCR extraction applies conservative NFKC/control-character normalization.
- Page and slide fragments are coalesced only within their original visual unit;
  regression tests reject cross-page and cross-slide citation anchors.
- The ingestion pipeline version advances to `1.3.0`, causing immutable reprocessing
  rather than mutating or silently reusing a `1.2.0` content version.
- Frontend tests, ESLint, production build, backend unit tests, Ruff, mypy, contract
  validation and production dependency audit pass on 2026-09-13.
- Local Kind verification deployed the Web, Agent and worker through Helm revision 5,
  built and published a pipeline `1.3.0` course version with 893 indexed chunks, and
  confirmed in the browser that TeX renders without literal delimiters and the cited
  Unit 1 material resolves to the exact `page 7` anchor.
- A later deployment-drift check found revision 6 had reused a pre-KaTeX Web image.
  The Web image was rebuilt with a distinct tag and Helm revision 7 verified that its
  production bundle contains the KaTeX renderer, stylesheet and fonts.
- The Hessian matrix reported during UI testing retained the correct `\\` source row
  separator. A browser render comparison isolated KaTeX's default array spacing as
  the overlap cause; global `arraystretch=1.6` and display overflow handling correct
  the fraction-heavy matrix layout.
- Helm revision 8 deployed the distinct `task15-math-spacing` Web image and its live
  production bundle was verified to contain both the `arraystretch` setting and the
  responsive equation overflow styles.
- A later deployment audit found that the live Web Pod had reused an older local-tag
  image whose production bundle did not contain Markdown or KaTeX. The Web image was
  rebuilt with an explicit `task15-math` tag and deployed through Helm revision 7;
  the live bundle now includes the KaTeX JavaScript, stylesheet and font assets.
- Formula images, diagrams and irrecoverably mis-mapped custom-font glyphs remain a
  deliberately separate multimodal-ingestion enhancement.
