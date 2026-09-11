# TASK-14 — Course Bootstrap and End-to-End Validation

**Status:** ready
**Priority:** P0
**Depends on:** TASK-03, TASK-04, TASK-13

## Goal

Turn a healthy local-real deployment into a usable tutor by registering an explicit
University of Leeds AI MSc course mapping, ingesting and publishing its material, and
verifying course selection and grounded chat through the Web UI.

## Scope

- Add an idempotent administration CLI or script that registers a programme, course,
  course run and validated read-only SourceRoot through the canonical Agent APIs.
- Require an explicit mapping from a module directory to programme/course/run IDs.
  Do not infer tenancy or ownership by scanning arbitrary NAS folder names.
- Keep machine-specific paths and private course metadata in an untracked local input;
  provide only a synthetic example in Git.
- Support manual ingestion trigger, bounded polling, actionable failure output and
  retry through the existing ingestion lifecycle APIs.
- Report the resulting immutable content version and require an explicit `--publish`
  action before swapping the active version. Do not silently auto-publish new NAS
  content.
- Make reruns safe: unchanged inputs must not duplicate programme, course, run,
  SourceRoot, chunks, artifacts or vectors.
- Verify that the published course appears in `GET /v1/courses` and in the React course
  selector.
- Add a local end-to-end check that submits an in-scope question, receives streamed
  output from the real LM Studio provider and validates at least one citation against
  the published course version.
- Document how to inspect ingestion status, preview a READY version, publish, retry,
  roll back and remove only generated test/bootstrap records.

## Deliverables

- Idempotent course bootstrap/ingestion CLI or script with unit tests.
- Synthetic example mapping and documented untracked local configuration format.
- A browser/API end-to-end verification script and operator runbook.
- A dated, redacted verification record for at least one Leeds AI MSc module.

## Acceptance criteria

- Running bootstrap twice returns the same logical programme, course, course run and
  SourceRoot without creating duplicates.
- A changed source snapshot creates one new immutable content version; an unchanged
  rerun does not create duplicate content.
- The command waits until ingestion reaches `READY` or exits non-zero with the failed
  item and retry guidance.
- Publication is explicit, and the prior published version remains available for
  rollback.
- After publication, the Web UI lists and selects the course and enables the chat
  input.
- One real-provider chat streams an answer and emits a citation belonging to the exact
  active course version. An unrelated question follows the configured abstention
  policy.
- No course document, learner data, access token, SMB credential or local configuration
  is committed or emitted into CI artifacts.

## Verification

```bash
scripts/course-bootstrap.sh --config .local/leeds-course.yaml
scripts/course-bootstrap.sh --config .local/leeds-course.yaml
scripts/course-bootstrap.sh --config .local/leeds-course.yaml --ingest --wait
scripts/course-bootstrap.sh --config .local/leeds-course.yaml --publish
scripts/local-course-e2e.sh --config .local/leeds-course.yaml
```

Completion requires API and browser evidence that the course is selectable and a
grounded chat succeeds against the published version. A health-only Helm smoke test is
not sufficient evidence for this task.
