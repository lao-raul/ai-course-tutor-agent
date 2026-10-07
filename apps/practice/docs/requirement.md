# Application Name:  Hiruzen
## Components:
- Category
- Search by(module/publisher/grade...)
- Courses for each book
- Generate Practice(Questions/Answers)
- Ask in line & live chat robot
- Study status/Resume studying
## All books placed in NAS `/var/services/homes/lvjial/ChinaTextbook`

## Confirmed first-release decisions — 2026-10-07

- ADR-006 and independent Hiruzen API/worker Deployments are accepted. The current
  two-container backend Pod is a transition state.
- The first release covers ChinaTextbook only; University of Leeds content is outside
  the initial Hiruzen catalog rollout.
- The source is mounted read-only on the development Mac at
  `/Volumes/home/ChinaTextbook`.
- The learning model is Book -> default StudyPlan -> Chapter/Topic, with optional
  associations to Agent CourseRuns.
- MVP question types are multiple choice, true/false, fill-in-the-blank and short
  answer.
- The default answer-release policy gives progressively stronger hints after the first
  and second incorrect attempts, then releases the answer/rationale after the third
  incorrect attempt or an explicit give-up action.
- Users can select Chinese, English or bilingual output; the default is Chinese.
- The first quality pilot is the primary-school English Foreign Language Teaching and
  Research Press (FLTRP/外研社) family.

The corpus contains four distinct primary-school FLTRP series. The exact first
golden-set volume is fixed below as test-data configuration rather than a change to the
accepted product model. See [china-textbook-inventory.md](china-textbook-inventory.md).

## Accepted implementation defaults — 2026-10-07

- The first release is a single local tenant. Every authenticated learner in that
  tenant can browse every published ChinaTextbook K-12 Book.
- One complete textbook PDF is one Book volume. Approving a valid candidate creates a
  system-managed Agent Course/CourseRun, queues ingestion and keeps the Book hidden
  until an administrator publishes a READY ContentVersion.
- Every candidate is staged. Administrators may batch-approve unambiguous candidates;
  candidates with parser issues require corrected metadata before approval.
- The first release exposes only a deterministic default StudyPlan. Instructor-authored
  StudyPlan editing is deferred.
- Agent extracts Chapter/Topic candidates from PDF table-of-contents and heading
  structure. If no reliable outline exists, Hiruzen exposes a book-level StudyPlan and
  never asks the LLM to invent chapters or learning objectives.
- The first golden-set volume is `外研社版（三年级起点）（主编：陈琳）/三年级上册`.
- Local/CI authentication keeps the existing bearer/JWT provider. Production OIDC
  issuer, audience and claim mapping remain deployment configuration required before
  production activation.
- Generation defaults to five questions, supports 1–20, uses difficulty values
  `introductory`, `standard` and `challenge`, and keeps UI language separate from
  question language.
