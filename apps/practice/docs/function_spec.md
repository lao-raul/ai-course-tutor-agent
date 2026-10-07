# Hiruzen Function Specification

**Status:** accepted v0.3 baseline; implementation in progress (TASK-18)  
**Updated:** 2026-10-07  
**Application:** `apps/practice` / `practice-api`  
**Parent specifications:**
[platform function spec](../../../docs/function-spec.md),
[platform design spec](../../../docs/design-spec.md)  
**Architecture:** [Hiruzen design spec](design_spec.md)
**Traceability:** [requirements-traceability.md](requirements-traceability.md)

## 1. Product outcome

Hiruzen turns an authorized textbook into a structured practice experience. A learner
can find a book, select its course or study plan, generate grounded exercises, ask for
help without leaking answers, review results and resume at the last meaningful point.

Hiruzen complements the Agent application rather than replacing it:

- Agent owns textbook catalog/content, immutable content versions, authorization,
  retrieval and cited tutoring chat.
- Hiruzen owns practice generation jobs, generated exercises, attempts, evaluation,
  study progress and resume state.

### 1.1 First-release scope

- Content catalog: ChinaTextbook K-12 only; University of Leeds is excluded.
- Development source mount: `/Volumes/home/ChinaTextbook`, read-only.
- Initial quality pilot: primary-school English FLTRP/外研社 series; the first golden-set
  volume is the Chen Lin Grade-3-start Grade 3 first-term book.
- Learning model: Book -> default StudyPlan -> Chapter/Topic.
- Access model: one local tenant; every authenticated learner can browse every published
  ChinaTextbook K-12 Book in that tenant.
- Activation model: one complete PDF is one Book volume. Approval creates a
  system-managed Agent Course/CourseRun and queues ingestion; search visibility begins
  only after an administrator publishes a READY ContentVersion.
- Authorization model: a published system-managed textbook CourseRun uses
  `tenant_authenticated` access, so every authenticated learner in the same tenant can
  retrieve/chat against it; normal instructor-managed courses retain membership ACLs.
- StudyPlan authoring: first release provides deterministic default plans only;
  instructor-authored plans are deferred.
- Response language: user-selectable Chinese, English or bilingual; default Chinese.
- Answer release: progressive hints for attempts one and two, then answer/rationale
  after the third incorrect attempt or explicit give-up.

## 2. Users and authorization

| Role | Capabilities |
|---|---|
| Learner | Search authorized books, generate personal practice, answer, request hints, view own progress and resume |
| Teaching assistant | Learner capabilities plus preview permitted course practice according to tenant policy |
| Instructor | Preview answer keys and inspect course-level quality reports; authored StudyPlan editing is post-MVP |
| Platform admin | Manage catalog import policy and operational configuration within the tenant boundary |

Identity, tenant, role, course membership and access rank come from verified tokens and
Agent authorization responses. Request fields cannot raise privilege.

## 3. Domain language

| Entity | Owner | Meaning |
|---|---|---|
| Category | Agent | Hierarchical or faceted grouping such as education level or subject |
| Book | Agent | A catalog entry linked to one or more published content versions |
| Course/CourseRun | Agent | Authorized teaching context associated with one or more books |
| StudyPlan | Hiruzen | Ordered practice objectives/modules for a book and course |
| GenerationJob | Hiruzen | Asynchronous request to retrieve evidence and generate a practice set |
| PracticeSet | Hiruzen | Immutable generated set pinned to content, model and prompt versions |
| Exercise | Hiruzen | Question, type, difficulty, evidence citations and protected answer material |
| Attempt | Hiruzen | One learner submission and server-side evaluation result |
| StudyProgress | Hiruzen | Derived completion/mastery summary and resume cursor |

The UI may call a StudyPlan a “course”, but API/domain identifiers keep it distinct
from the Agent-owned academic Course.

## 4. Functional requirements

### 4.1 Catalog and categories

| ID | Requirement |
|---|---|
| HFR-CAT-1 | A user can browse a tenant-scoped category hierarchy and facet counts. |
| HFR-CAT-2 | A user can search authorized books by free text and filter by education level, grade, subject/module, publisher, edition, term/volume and language. |
| HFR-CAT-3 | Search uses cursor pagination and deterministic normalized-title/edition/Book-ID ordering, and never returns an unpublished or unauthorized content resource. |
| HFR-CAT-4 | A book detail includes title, publisher, grade, subject/module, edition, term/volume, language, optional cover/ISBN, ingestion state and available course/run associations. |
| HFR-CAT-5 | Every NAS candidate is staged. Admins may batch-approve unambiguous candidates; candidates with parser issues require corrected metadata and can never be published silently. |
| HFR-CAT-6 | Catalog results use Agent-issued IDs; filesystem paths and NAS credentials are never returned. |

### 4.2 Courses and study plans

| ID | Requirement |
|---|---|
| HFR-COURSE-1 | A user can list authorized Agent CourseRuns associated with a selected book. |
| HFR-COURSE-2 | First release exposes one deterministic default StudyPlan per Book. Instructor-authored plans are a post-MVP extension. |
| HFR-COURSE-3 | A StudyPlan references Agent `book_id`, `course_id` and, at generation time, the exact published `content_version_id`; it does not copy textbook content. |
| HFR-COURSE-4 | Agent-provided PDF outline metadata supplies Chapter/Topic entries. If no reliable outline exists, Hiruzen provides a book-level plan without inventing chapters or learning objectives. |

### 4.3 Practice generation

| ID | Requirement |
|---|---|
| HFR-GEN-1 | A learner can request 1–20 questions for a Book, defaulting to 5, with optional system CourseRun, StudyPlan topic/module, `introductory`/`standard`/`challenge` difficulty and allowed question types. |
| HFR-GEN-2 | Generation returns an accepted job promptly; status can be polled until `READY`, `FAILED` or `CANCELLED`. |
| HFR-GEN-3 | Agent performs authorization and evidence retrieval against the currently published content version before any LLM generation. |
| HFR-GEN-4 | Every accepted exercise contains at least one valid evidence citation; its answer and rationale must be supportable by those cited chunks. |
| HFR-GEN-5 | Generation output passes strict schema, count, type, citation, answerability, duplicate and answer-leakage validation before becoming `READY`. |
| HFR-GEN-6 | The stored PracticeSet records content version, evidence chunk IDs, prompt version, generation model, validation version, random seed and correlation ID. |
| HFR-GEN-7 | Identical idempotency keys return the existing job/set and never create duplicate work. |
| HFR-GEN-8 | If evidence is insufficient, Hiruzen fails transparently with a retryable/non-retryable reason rather than generating unsupported questions. |
| HFR-GEN-9 | Student retrieval never exposes protected answers, rationales or solution-bearing evidence before the applicable submit/release policy permits it. |
| HFR-GEN-10 | Instructor preview is clearly labeled AI-generated and is not automatically published as official assessment material. |
| HFR-GEN-11 | The learner can select Chinese, English or bilingual generation; omitted language defaults to Chinese. |

MVP question types are:

- multiple choice with one unambiguous correct option;
- true/false;
- fill-in-the-blank with normalized acceptable answers;
- short answer with a bounded rubric and exemplar answer.

The strict schemas use a discriminated `type` field. All questions contain prompt,
difficulty, language and one or more evidence citation IDs. Multiple choice has 2–6
stable option IDs and exactly one protected correct option. True/false has one protected
boolean answer. Fill-in-the-blank has 1–10 protected normalized acceptable answers.
Short answer has 1–5 weighted rubric criteria, weights totaling 1, a protected exemplar
and a default provisional pass threshold of 0.70.

### 4.4 Answering and feedback

| ID | Requirement |
|---|---|
| HFR-ANS-1 | A learner can submit an answer once or repeatedly according to the StudyPlan policy; submission is idempotent. |
| HFR-ANS-2 | Objective types are evaluated deterministically where possible. Short answers use rubric-constrained LLM evaluation and are labeled provisional. |
| HFR-ANS-3 | Feedback distinguishes correctness, hint, rationale and cited source; answer keys remain server-side until release. |
| HFR-ANS-4 | Attempt records preserve question revision, submitted value, evaluation result, evaluator/model version and timestamps. |
| HFR-ANS-5 | A learner can report an incorrect, ambiguous or unsafe question for instructor review. |
| HFR-ANS-6 | The default policy releases progressively stronger hints after incorrect attempts one and two, and releases the answer/rationale after incorrect attempt three or explicit give-up. |

### 4.5 Inline ask and live tutoring chat

| ID | Requirement |
|---|---|
| HFR-CHAT-1 | A learner can ask about the current exercise or selected question text inline. |
| HFR-CHAT-2 | The Web client uses Agent's existing grounded SSE endpoint with the same user identity, course ID, `assessment_mode=true` and attempt number. |
| HFR-CHAT-3 | Hiruzen does not proxy or duplicate Agent retrieval/chat unless a future network boundary requires a dedicated streaming gateway. |
| HFR-CHAT-4 | Agent applies teaching policy and withholds stored solution chunks until the configured attempt/release rule allows them. |
| HFR-CHAT-5 | Chat citations resolve to the exact published textbook content; generated exercise text is context, not an authoritative source. |
| HFR-CHAT-6 | Live chat remains a separate Agent chat session but may carry a non-sensitive Hiruzen correlation/context ID for navigation and tracing. |

### 4.6 Study status and resume

| ID | Requirement |
|---|---|
| HFR-PROG-1 | Hiruzen records `NOT_STARTED`, `IN_PROGRESS` or `COMPLETED` per learner and StudyPlan/PracticeSet. |
| HFR-PROG-2 | Progress includes completed/total questions, correct/attempted counts, latest activity, topic-level mastery signals and the next resumable item. |
| HFR-PROG-3 | Resume returns the most recent accessible StudyPlan, PracticeSet, exercise position and safe UI state without returning an answer key. |
| HFR-PROG-4 | Progress updates are derived from immutable attempts and idempotent activity events so retries cannot inflate completion or scores. |
| HFR-PROG-5 | A learner can reset a resume cursor without deleting attempt history; deletion/export follows platform privacy policy. |
| HFR-PROG-6 | Only compact mastery/progress signals may be shared with Agent memory, with learner consent and through a versioned API/event contract. |

## 5. API capability baseline

The exact OpenAPI file will be updated during implementation. The approved operation
boundary is:

| Operation | Method/path | Owner |
|---|---|---|
| `listPracticeCategories` | `GET /v1/practice/catalog/categories` | Hiruzen facade over Agent catalog |
| `searchPracticeBooks` | `GET /v1/practice/catalog/books` | Hiruzen facade over Agent catalog |
| `getPracticeBook` | `GET /v1/practice/catalog/books/{book_id}` | Hiruzen facade over Agent catalog |
| `listBookCourses` | `GET /v1/practice/catalog/books/{book_id}/courses` | Hiruzen facade over Agent catalog |
| `getBookStudyPlan` | `GET /v1/practice/catalog/books/{book_id}/study-plan` | Hiruzen |
| `createPracticeGeneration` | `POST /v1/practice/catalog/books/{book_id}/generations` | Hiruzen |
| `getPracticeGeneration` | `GET /v1/practice/generations/{generation_id}` | Hiruzen |
| `cancelPracticeGeneration` | `POST /v1/practice/generations/{generation_id}/cancel` | Hiruzen |
| `getPracticeSet` | `GET /v1/practice/sets/{set_id}` | Hiruzen |
| `previewPracticeSet` | `GET /v1/practice/sets/{set_id}/preview` | Hiruzen instructor read model |
| `submitPracticeAnswer` | `POST /v1/practice/sets/{set_id}/exercises/{exercise_id}/attempts` | Hiruzen |
| `giveUpPracticeExercise` | `POST /v1/practice/sets/{set_id}/exercises/{exercise_id}/give-up` | Hiruzen |
| `getStudyStatus` | `GET /v1/practice/study-status` | Hiruzen |
| `resumeStudy` | `GET /v1/practice/resume` | Hiruzen |
| `resetResumeCursor` | `DELETE /v1/practice/resume` | Hiruzen |
| `reportPracticeExercise` | `POST /v1/practice/exercises/{exercise_id}/reports` | Hiruzen |

Agent additions required by this specification are versioned catalog operations and a
service-authorized evidence retrieval operation. Hiruzen must not call Agent internal
Python modules.

The v0.2 `POST /v1/practice/courses/{course_id}/exercises:generate` operation remains a
deprecated compatibility alias for one contract version after H1–H3; it resolves the
Book binding and submits the same asynchronous generation command.

The canonical Book generation body may include `course_id` and `study_plan_id`; when
omitted, Hiruzen uses the Book's system-managed CourseRun and default StudyPlan.

## 6. Generation and evaluation states

```text
QUEUED -> RETRIEVING -> GENERATING -> VALIDATING -> READY
   |           |             |             |
   +-----------+-------------+-------------+-> FAILED
   +-----------------------------------------> CANCELLED
```

`READY` PracticeSets are immutable. Regeneration creates a new set/revision and keeps
the original attempt history reproducible.

## 7. Non-functional requirements

| ID | Requirement/target |
|---|---|
| HNFR-1 | Catalog/search P95 ≤ 500 ms and resume P95 ≤ 300 ms on the approved LAN baseline, excluding first-time cache warm-up. |
| HNFR-2 | Generation submission P95 ≤ 1 s; generation runs asynchronously with a configured deadline and no indefinitely held HTTP request. |
| HNFR-3 | 100% of READY exercises pass JSON/schema and citation-ID validation; generated-set evidence coverage is 100%. |
| HNFR-4 | On the approved golden set, answer-key groundedness ≥ 0.95, duplicate rate ≤ 0.02 and invalid/ambiguous-question rate ≤ 0.05. |
| HNFR-5 | Practice API availability target is 99.5%; an Agent or LLM outage degrades generation/chat but cataloged progress remains readable. |
| HNFR-6 | API and workers are horizontally scalable; jobs and submissions are idempotent and safe under at-least-once delivery. |
| HNFR-7 | Logs/traces never contain answer keys, raw textbook text, full prompts or learner responses by default. |
| HNFR-8 | Practice data uses a separately owned schema/role and can later move to an independent PostgreSQL service without API changes. |
| HNFR-9 | Every request/job propagates a correlation ID across Web, Hiruzen, Agent and LM Studio. |
| HNFR-10 | CI uses generated fixtures and deterministic providers; it never contacts the home NAS or LAN LM Studio. |
| HNFR-11 | Production workloads run non-root with resource limits, probes, secret references and least-privilege network policies under the platform Helm chart. |

## 8. Acceptance criteria

The first production-capable Hiruzen release is acceptable when:

1. An authorized learner can filter a generated/approved catalog by grade, publisher
   and subject, open a book and see associated courses.
2. A request produces a READY grounded PracticeSet or a transparent failure; every
   question has valid citations and no student response leaks its answer.
3. Objective answers are scored deterministically and short-answer grading is labeled
   provisional with stored evaluator provenance.
4. Inline/live help streams through Agent and follows solution-release policy.
5. A learner can leave, return and resume the exact next safe exercise.
6. Cross-tenant, unauthorized-course, answer-leakage and replay tests fail closed.
7. Golden-set generation quality, Agent retrieval, integration/E2E, migration, Helm
   and observability gates pass in CI.

## 9. Explicit non-goals

Hiruzen is not an official assessment authority, a second content-ingestion service,
a second RAG implementation or a direct NAS browser. It never modifies source books
and never treats an LLM-generated answer as authoritative without evidence and policy
validation.
