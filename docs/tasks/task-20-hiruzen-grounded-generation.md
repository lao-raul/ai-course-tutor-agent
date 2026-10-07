# TASK-20 — Hiruzen Grounded Practice Generation

**Status:** planned  
**Priority:** P0  
**Depends on:** TASK-18, TASK-19

## Goal

Generate schema-valid exercises only from Agent-authorized evidence pinned to an
immutable published content version.

## Scope

- Add Agent delegated evidence retrieval contract with ACL/content-version enforcement.
- Add Chinese, English and bilingual structured generation prompts; default Chinese.
- Validate count, type, citations, answerability, duplicates and answer leakage.
- Implement one bounded repair attempt and sanitized terminal failure reasons.
- Capture seed, prompt/model/validator versions and correlation/retrieval trace IDs.

## Deliverable artifacts

| Artifact | Repository path |
|---|---|
| Delegated evidence DTO/OpenAPI contract | `packages/contracts/src/course_tutor_contracts/practice_evidence.py`, `packages/contracts/openapi/agent-api.v1.json` |
| Agent evidence endpoint | `apps/api/src/course_tutor_api/routes/practice_evidence.py` |
| Hiruzen Agent/inference adapters | `apps/practice/src/course_tutor_practice/adapters/{agent_client,inference}.py` |
| Versioned prompts and JSON schemas | `apps/practice/src/course_tutor_practice/generation/` |
| Deterministic generation validators | `apps/practice/src/course_tutor_practice/application/validation.py` |
| Generated fixtures and golden-set manifest | `tests/fixtures/hiruzen/`, `tests/evaluation/hiruzen/` |
| Security, contract and generation tests | `tests/{unit,integration,e2e}/practice/` |
| Completion evidence | `docs/verification/<date>-task-20.md` |

## Acceptance criteria

- **AC-20.1:** Every READY exercise has a valid evidence citation and supportable protected answer.
- **AC-20.2:** Insufficient or unauthorized evidence fails closed without persisting questions.
- **AC-20.3:** Multiple choice, true/false, fill-in-the-blank and short-answer outputs pass
  strict schemas and requested count/type checks.
- **AC-20.4:** Chinese, English and bilingual generation work, with Chinese used when omitted.
- **AC-20.5:** Repair is attempted at most once and terminal errors contain no prompt,
  textbook text or protected answer.
- **AC-20.6:** Deterministic fake-provider CI and the selected Chen Lin Grade 3
  first-term real-pilot acceptance both pass.

## Independent delivery boundary

TASK-20 owns the additive Agent evidence contract and the adapters/validators behind
TASK-19's worker ports. It does not alter StudyPlan/job persistence semantics or
attempt/progress APIs.

## Verification

```bash
uv run pytest tests/unit/practice tests/integration/practice tests/e2e/practice -q
uv run python tests/evaluation/hiruzen/run.py --provider fake
uv run python scripts/validate_hiruzen_baseline.py
```

The selected real FLTRP golden set remains a manual, redacted acceptance run.
