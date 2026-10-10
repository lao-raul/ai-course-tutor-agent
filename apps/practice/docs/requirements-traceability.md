# Hiruzen Requirements Traceability — v0.3

**Status:** active  
**Updated:** 2026-10-10

This matrix is the delivery source of truth for Hiruzen requirements. Operation IDs
refer to the approved operation boundary in the Hiruzen function/design specifications;
they become canonical OpenAPI operations in the task that implements them.

| Requirement | Implementation task | Operation IDs | Verification | Current status |
|---|---|---|---|---|
| HFR-CAT-1 | TASK-18 | listPracticeCategories, listCatalogCategories | catalog hierarchy/facet contract tests | implemented |
| HFR-CAT-2 | TASK-18 | searchPracticeBooks, searchCatalogBooks | filter, Unicode search and pagination tests | implemented |
| HFR-CAT-3 | TASK-18 | searchPracticeBooks, searchCatalogBooks | unpublished/unauthorized and stable-sort tests | implemented |
| HFR-CAT-4 | TASK-18 | getPracticeBook, getCatalogBook | book detail contract tests | implemented |
| HFR-CAT-5 | TASK-18 | createCatalogImport, listCatalogImportCandidates, updateCatalogImportCandidate, approveCatalogImportCandidate, rejectCatalogImportCandidate | scanner quarantine, correction and approval tests | implemented |
| HFR-CAT-6 | TASK-18 | searchPracticeBooks, getPracticeBook | path/credential response leakage tests | implemented |
| HFR-COURSE-1 | TASK-18 | listBookCourses, listCatalogBookCourses | delegated authorization tests | implemented |
| HFR-COURSE-2 | TASK-19 | getBookStudyPlan | deterministic default StudyPlan ordering/policy tests | implemented |
| HFR-COURSE-3 | TASK-19, TASK-20 | createPracticeGeneration, retrievePracticeEvidence | immutable Agent ID/version reference tests | implemented |
| HFR-COURSE-4 | TASK-19, TASK-24 | getCatalogBookOutline, getBookStudyPlan, createPracticeGeneration | deterministic outline extraction/API plus outline-derived and book-level fallback plan tests | implemented |
| HFR-GEN-1 | TASK-19, TASK-20 | createPracticeGeneration | request boundary/type/count tests | implemented |
| HFR-GEN-2 | TASK-19 | createPracticeGeneration, getPracticeGeneration, cancelPracticeGeneration | asynchronous state-machine/cancellation tests | implemented |
| HFR-GEN-3 | TASK-20 | retrievePracticeEvidence | delegated authorization/content-version tests | implemented |
| HFR-GEN-4 | TASK-20 | getPracticeSet, retrievePracticeEvidence | citation and deterministic answer-support gates; semantic golden review remains HNFR-4 | implemented |
| HFR-GEN-5 | TASK-20 | getPracticeGeneration | schema/count/type/duplicate/leakage tests | implemented |
| HFR-GEN-6 | TASK-19, TASK-20 | getPracticeSet | reproducibility metadata persistence tests | implemented |
| HFR-GEN-7 | TASK-19 | createPracticeGeneration | replay/concurrent idempotency tests | implemented |
| HFR-GEN-8 | TASK-20 | getPracticeGeneration | insufficient-evidence failure tests | implemented |
| HFR-GEN-9 | TASK-20, TASK-21 | getPracticeSet, submitPracticeAnswer | protected-answer leakage matrix | planned |
| HFR-GEN-10 | TASK-20, TASK-22 | previewPracticeSet | instructor preview labeling/audit tests | planned |
| HFR-GEN-11 | TASK-20, TASK-22 | createPracticeGeneration | API Chinese-default and three-language tests; learner UI remains TASK-22 | in_progress |
| HFR-ANS-1 | TASK-21 | submitPracticeAnswer | submission replay/policy tests | planned |
| HFR-ANS-2 | TASK-21 | submitPracticeAnswer | deterministic and provisional grading tests | planned |
| HFR-ANS-3 | TASK-21 | submitPracticeAnswer | staged feedback/release tests | planned |
| HFR-ANS-4 | TASK-21 | submitPracticeAnswer | immutable attempt provenance tests | planned |
| HFR-ANS-5 | TASK-21 | reportPracticeExercise | learner report/moderation tests | planned |
| HFR-ANS-6 | TASK-21 | submitPracticeAnswer, giveUpPracticeExercise | attempts 1/2 hints and attempt 3/give-up release matrix | planned |
| HFR-CHAT-1 | TASK-22 | streamCourseChat | inline question browser E2E | planned |
| HFR-CHAT-2 | TASK-22 | streamCourseChat | assessment context/SSE contract tests | planned |
| HFR-CHAT-3 | TASK-22 | streamCourseChat | architecture dependency and network-call tests | planned |
| HFR-CHAT-4 | TASK-20, TASK-22 | streamCourseChat | solution withholding/release tests | planned |
| HFR-CHAT-5 | TASK-20, TASK-22 | streamCourseChat | published-version citation tests | planned |
| HFR-CHAT-6 | TASK-22 | streamCourseChat | session/correlation propagation tests | planned |
| HFR-PROG-1 | TASK-21 | getStudyStatus | status transition tests | planned |
| HFR-PROG-2 | TASK-21 | getStudyStatus | counters/mastery projection tests | planned |
| HFR-PROG-3 | TASK-21 | resumeStudy | safe authorization-aware resume tests | planned |
| HFR-PROG-4 | TASK-21 | submitPracticeAnswer, getStudyStatus | replay and projection rebuild tests | planned |
| HFR-PROG-5 | TASK-21 | resumeStudy, resetResumeCursor | cursor reset/history retention tests | planned |
| HFR-PROG-6 | TASK-21 | getStudyStatus | consent and compact-memory contract tests | planned |
| HNFR-1 | TASK-18, TASK-21, TASK-23 | searchPracticeBooks, resumeStudy | LAN performance benchmark | planned |
| HNFR-2 | TASK-19, TASK-23 | createPracticeGeneration | submission latency/deadline tests | planned |
| HNFR-3 | TASK-20, TASK-23 | getPracticeSet | fake schema/evidence coverage gate implemented; release-wide gate remains TASK-23 | in_progress |
| HNFR-4 | TASK-20, TASK-23 | getPracticeSet | approved FLTRP golden-set report | planned |
| HNFR-5 | TASK-19, TASK-21, TASK-23 | getPracticeGeneration, getStudyStatus | dependency outage and availability drills | planned |
| HNFR-6 | TASK-19, TASK-23 | createPracticeGeneration, submitPracticeAnswer | horizontal-scale/replay tests | planned |
| HNFR-7 | TASK-20, TASK-21, TASK-23, TASK-24 | getCatalogBookOutline, createPracticeGeneration, submitPracticeAnswer | outline and practice telemetry redaction tests | planned |
| HNFR-8 | TASK-19, TASK-23 | createPracticeGeneration | schema ownership/migration tests | planned |
| HNFR-9 | TASK-18, TASK-19, TASK-20, TASK-23 | createPracticeGeneration, retrievePracticeEvidence | job-to-Agent and LM Studio correlation implemented; release-wide trace gate remains TASK-23 | in_progress |
| HNFR-10 | TASK-18, TASK-20, TASK-23, TASK-24 | searchPracticeBooks, getCatalogBookOutline, createPracticeGeneration | hosted-CI network isolation tests | planned |
| HNFR-11 | TASK-23 | practiceHealth, practiceReady | Helm/Kind security and policy tests | planned |

## Machine validation

```bash
uv run python scripts/validate_hiruzen_baseline.py
```

The validator fails if a requirement is missing, a task file is unknown, an operation
is absent from the accepted specs, or a row has no verification/status.
