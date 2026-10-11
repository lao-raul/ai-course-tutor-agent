# Practice question-form and dialogue-pairing regression — 2026-10-13

## Defect and repair

- A `true_false` exercise was stored as an interrogative prompt asking the learner
  for the correct answer. The validator now requires a declarative stem and
  asks the model to repair rejected drafts.
- A later 20-question set contained a `true_false` prompt ending in a colon
  (`当你向别人介绍父亲时，可能会说：`) with no claim to judge. Its following
  `fill_in_the_blank` exercise asked an open question without a blank. The
  validator and deployed-API probe now reject both forms and supply type-specific
  repair guidance to the model. Existing immutable sets are not rewritten.
- Page-level evidence can contain unrelated dialogue turns. The generator is
  instructed not to join two separately quoted turns as an assumed question/
  answer pair; the validator rejects that shape and obvious greeting/yes-no
  answers to object-identification questions. This is deliberately a narrow
  mechanical guard, not a general semantic truth judge.
- `scripts/verify_practice_generation_api.py` exercises the real HTTP generation
  and set endpoints, saves the learner-visible response to a private gitignored
  report, and audits count, exact duplicate stems, resolved citations, malformed
  true/false prompts, missing fill-in-the-blank placeholders and the unverified
  quoted-turn pattern.
- `scripts/deploy-and-verify-practice.sh` rebuilds and Helm-upgrades only the
  changed Practice Worker in an existing local Kind release before that API test.

## Verification

- Unit tests covering both rejected defects, a valid quoted question inside a
  declarative claim, the worker repair loop and API probe: passed locally.
- The first 20-question run with the true/false fix only reached READY and the
  API audit passed. A deliberately broader dialogue-pairing rejection rule then
  caused both 20- and 5-question runs to fail validation; it was narrowed before
  the final deployment rather than accepted as a release-quality result.
- Final local Helm revision **23**, image
  `course-tutor-practice-worker:dialogue-compat-20261013`: Worker rollout passed.
- Final real textbook API generation
  `7705d70c-5bba-5a89-8944-b657be79ac62` reached **READY** with 20 exercises;
  the mechanical response audit reported **0 errors**. Its full response is
  stored only in the gitignored `build/reports/practice-generation-7705d70c-5bba-5a89-8944-b657be79ac62.json`.
- The question-form repair was deployed as local Helm revision **27** with image
  `course-tutor-practice-worker:question-form-20261013`. Targeted real-book
  generations `eeb927d4-8da6-581b-bb46-b6d44fa88a8c` (3 true/false) and
  `65155371-0552-5d62-bb7b-2d2b74d94db8` (3 fill-in-the-blank) both reached
  **READY**, and both API audits reported **0 mechanical errors**. A mixed 5-question
  generation `e275398d-4a74-57e5-8953-c9ceeb92585e` also reached READY.
- The first mixed 20-question run on this image,
  `3256ddc3-0dc8-517e-8373-3cf158bdba3a`, **failed** with
  `validation_failed`: most first-pass drafts tested activity headings, and bounded
  top-ups accepted only 9 of 20. This is not counted as a 20-question pass.

## Limits

- The learner API intentionally hides answer keys, so the response audit cannot
  certify answer correctness or semantic groundedness. A human reviewer must
  inspect the actual textbook and answer-release view before TASK-23 approval.
- Several questions in the final set test the same phrase through multiple
  types or slightly different wording. Exact duplicate detection does not
  measure the semantic duplicate rate required by HNFR-4. The golden-set gate
  and named human approval remain pending.
- The targeted 3-question fill-in-the-blank set contains two semantically
  similar prompts about asking what an object is; the zero-error structural
  audit does not imply diversity or pedagogical quality.
- This deployment uses uncommitted local source. Hosted CI for this exact change
  has not run; the local image tag is not a published immutable digest.

## 20-question validation-failure replay

- User-reported job `91885986-40e6-5bd0-9bdc-339156cc0810` failed after
  accepting only 1/20 first-pass drafts. The broad metadata filter treated
  page/activity references as questions *about* those headings; bounded
  one-at-a-time top-ups ended at 14/20. The filter now distinguishes contextual
  navigation references from title/heading questions, while retaining a narrow
  guard for questions that ask whether an activity heading appears.
- The first replay, `fc4d7730-585c-585b-af42-8d14c227631e`, reached READY
  with 20 exercises and zero mechanical API-audit errors. A later random replay
  began with malformed JSON and reached 18/20 before the former five-minute
  job deadline; it failed `deadline_exceeded`. The worker now preserves
  individually schema-valid drafts, retries a wholly malformed first batch
  once, uses smaller rotating top-ups, and can safely rebind objective MC/blank
  answers to a supplied excerpt containing the exact answer string. A 20-question
  job has an eight-minute deadline; smaller jobs retain five minutes.
- Local Helm revision **31** runs Practice API image
  `course-tutor-practice:partial-batch-20261013` and Practice Worker image
  `course-tutor-practice-worker:citation-batch4-20261013`. The final real-book
  generation `640ea866-2a11-5bc6-8aee-43cae2c99c89` reached READY with 20
  exercises, including 9 true/false; the API audit reported **0 structural
  errors**. The full learner response is available only in gitignored
  `build/reports/practice-generation-640ea866-2a11-5bc6-8aee-43cae2c99c89.json`.
- Practice unit tests, lint, formatting, typing and script syntax passed locally.
  Docker's configured frontend mirror returned 502 twice; the final Worker was
  built successfully with the local legacy Docker builder. Hosted CI for these
  uncommitted changes has not run.
- The final 20-question set still repeats several learning objectives across
  multiple wording variants and question types. Its zero-error structural audit
  does **not** satisfy the semantic-diversity or human-review quality gate.

## Short-answer scoring availability

- The local runtime has an empty LM Studio API key. The rubric evaluator had
  sent `Authorization: Bearer ` even in that case, unlike the generation client.
  It now omits the Authorization header when no key is configured; nonempty
  keys retain bearer authentication. Unit tests cover both paths and invalid
  score rejection.
- The updated evaluator scored a direct request against the real LM Studio
  endpoint. Local Helm revision **32** deployed image
  `course-tutor-practice:rubric-empty-key-20261013` for Practice API, and its
  Deployment rollout passed. A short-answer submission to a separate test set
  (`d15a5314-a5e3-5066-afca-f0fbcaf50222`) returned HTTP success with
  `correct=true`, `score=1`, and `evaluator=rubric_llm`.
- The learner's reported set was not modified during verification. A failed
  scorer call occurs before `record_attempt`, so the earlier 503 did not consume
  an attempt. Hosted CI has not run for this uncommitted local change.
