# Known Issues

## KI-001 — Hiruzen generated-question ambiguity and grounding

- Status: open; remediation deferred by the owner on 2026-10-19 to advance other tasks.
- Related task: [TASK-23](tasks/task-23-hiruzen-deployment-and-quality-gates.md), AC-23.5.
- Issue summary: generated questions may infer unsupported teaching intent or
  inadequately handle alternative valid answers, despite passing structural checks.
- Impact: a structurally valid generated question can still be ambiguous or weakly
  grounded. Samples require teacher review before teaching use; no official assessment
  or automatic publication is authorized.
- Single detailed record: [TASK-23 remediation, current status and verification history](verification/2026-10-10-task-23.md).
  All sample outcomes, fixes, review decisions and evidence paths are maintained there.
  Answer-bearing sample files stay gitignored.
- Closure: add regression coverage for remaining defects, run a fresh fixed twenty-Unit
  sample, obtain named human review and pass the real golden gate. Preserve failed runs.
- Scheduling decision: this issue does not block independent TASK-25 implementation.
  Deferral is not a waiver of release quality gates or completion of TASK-23.
