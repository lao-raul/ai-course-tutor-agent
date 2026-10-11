# Hiruzen release-quality evidence

CI runs `run.py --provider fake` against synthetic text and never accesses the home NAS
or LM Studio. That gate checks deterministic structure and citations only. It is **not**
the real-book approval required by TASK-23.

For the selected **FLTRP Grade-3-start, Chen Lin, Grade 3 first term** book, a teacher
or designated reviewer must review at least 20 generated cases across chapters and
question types. Keep raw textbook passages, student answers and full prompts out of
the report. Record stable case IDs and the following booleans for each case:

`schema_valid`, `citation_valid`, `evidence_covered`, `answer_grounded`, `ambiguous`,
`duplicate`.

The JSON report must also contain:

- `book_family` exactly matching `manifest.json`'s `real_pilot.book_family`;
- exact `release_sha`, published `content_version_id`, `model_version` and
  `prompt_version`; `ready_exercise_count` must equal the reviewed-case count;
- `approval`: a named human `reviewer`, `decision: "approved"`, and ISO `reviewed_at`;
- `latency_ms`: at least 20 numeric samples each for `catalog_search`, `resume`, and
  `generation_submit`, measured on the approved LAN baseline;
- `operational_evidence`: measured `availability_percent` plus nonempty evidence IDs
  for `availability`, `worker_replay`, `log_redaction`, `schema_isolation`,
  `correlation`, `ci_isolation`, and `security`.

Run:

```bash
python3 tests/evaluation/hiruzen/golden_gate.py \
  --report <redacted-report.json> \
  --release-sha <published-40-character-sha> \
  --output build/reports/hiruzen-golden-gate.json
```

The gate enforces HNFR-1–4 numerical
thresholds and requires HNFR-5–11 evidence. Production deployment refuses to start
without a passing report supplied as `HIRUZEN_GOLDEN_REPORT`; the GitHub deployment
environment may provide `HIRUZEN_GOLDEN_REPORT_B64`. Keep the real report in a
restricted artifact store, not in this repository.
