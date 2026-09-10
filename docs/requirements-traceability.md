# Requirements Traceability — Baseline v0.2

**Status:** active
**Updated:** 2026-09-09

`Operation IDs` reference the canonical OpenAPI documents in `packages/contracts/openapi/`. `Verification` names an existing check or the task that must create it. A planned verification is not completion evidence.

| Requirement | Implementation task | Operation IDs | Verification | Current status |
|---|---|---|---|---|
| FR-1.1 | TASK-03 | createProgramme, createCourse | `tests/integration/ingestion/test_version_lifecycle.py` registration separation | implemented |
| FR-1.2 | TASK-03 | createCourseIngestion, getIngestion | `tests/integration/ingestion/test_version_lifecycle.py` add/edit/delete/rename | implemented |
| FR-1.3 | TASK-03, TASK-05 | createCourseIngestion | duplicate-delivery and concurrent `SKIP LOCKED` integration tests | implemented |
| FR-1.4 | TASK-03 | getIngestion, publishContentVersion, rollbackContentVersion | READY/publish/active-alias lifecycle integration test | implemented |
| FR-1.5 | TASK-03 | getIngestion, listCourseSources, retryIngestion | validation/dead-letter integration test; parser quarantine tests | implemented |
| FR-1.6 | TASK-02, TASK-03 | getCourseSource | canonical artifact round-trip and ACL matrix tests | implemented |
| FR-2.1 | TASK-02, TASK-04 | streamCourseChat | planned:TASK-04 authenticated bilingual chat test | partial |
| FR-2.2 | TASK-02, TASK-04 | streamCourseChat | `tests/unit/test_retrieval_acl.py`; security tenant tests | implemented |
| FR-2.3 | TASK-04, TASK-05 | streamCourseChat | planned:TASK-05 lexical+dense benchmark | partial |
| FR-2.4 | TASK-04, TASK-05 | streamCourseChat, getCourseSource | `tests/unit/retrieval/test_grounded_stream.py` citation permutation and UUID validation | implemented |
| FR-2.5 | TASK-04 | streamCourseChat | `tests/unit/retrieval/test_grounded_stream.py` first-token and hidden-trailer tests; Web Vitest | implemented |
| FR-2.6 | TASK-04, TASK-05 | streamCourseChat | planned:TASK-05 abstention precision/recall benchmark | partial |
| FR-2.7 | TASK-04 | streamCourseChat | retrieval trace candidate/evidence/timing fields and cancellation terminal-state test | implemented |
| FR-3.1 | TASK-06 | streamCourseChat | planned:TASK-06 education-level behavior tests | planned |
| FR-3.2 | TASK-06 | streamCourseChat | planned:TASK-06 cited study-material generation tests | planned |
| FR-3.3 | TASK-03, TASK-06 | streamCourseChat | planned:TASK-06 assessed-work hint policy test | failing-review |
| FR-3.4 | TASK-07 | getPracticeCapabilities, generatePracticeExercises | `apps/practice/tests/test_app.py` capability and deterministic-501 tests | implemented |
| FR-4.1 | TASK-06 | streamCourseChat | planned:TASK-06 session scope and token-budget test | planned |
| FR-4.2 | TASK-06 | listMemories | planned:TASK-06 opt-in and storage-policy test | planned |
| FR-4.3 | TASK-06 | listMemories | planned:TASK-06 memory candidate validation test | planned |
| FR-4.4 | TASK-06 | listMemories, updateMemory | planned:TASK-06 dedup/conflict/decay test | planned |
| FR-4.5 | TASK-06 | streamCourseChat | planned:TASK-06 recall ranking and budget test | planned |
| FR-4.6 | TASK-06 | listMemories, updateMemory | planned:TASK-06 correction/export/tombstone/purge test | planned |
| FR-5.1 | TASK-02 | agentHealth, practiceHealth | production local-auth rejection, shared bearer authentication and both security-schema tests | implemented |
| FR-5.2 | TASK-02 | listCourses, getCourse, streamCourseChat | tenant hiding, server-derived rank and crafted-body schema tests | implemented |
| FR-5.3 | TASK-02 | createCourse, createCourseIngestion, updateMemory | admin role/tenant/audit tests; memory action remains TASK-06 | partial |
| FR-5.4 | TASK-02, TASK-12 | agentReady, practiceReady | planned:TASK-12 sensitive-log/trace test | partial |
| FR-5.5 | TASK-06 | streamCourseChat | planned:TASK-06 AI-label and official-guidance test | planned |
| FR-6.1 | TASK-07, TASK-09 | practiceHealth | planned:TASK-09 independent rollout test | planned |
| FR-6.2 | TASK-07 | practiceHealth, practiceReady, getPracticeCapabilities | `apps/practice/tests/test_app.py` health/readiness/capabilities tests | implemented |
| FR-6.3 | TASK-02, TASK-07 | generatePracticeExercises | shared authentication plus course-scope and deterministic-501 tests | implemented |
| NFR-1 | TASK-09, TASK-12 | agentReady, practiceReady | planned:TASK-12 availability/failure test | planned |
| NFR-2 | TASK-04, TASK-12 | streamCourseChat | first-token-before-provider-completion regression; planned:TASK-12 TTFT load report | partial |
| NFR-3 | TASK-05 | streamCourseChat | planned:TASK-05 machine-readable RAG benchmark | planned |
| NFR-4 | TASK-03, TASK-05 | createCourseIngestion, getIngestion | duplicate-delivery and concurrent worker integration tests | implemented |
| NFR-5 | TASK-12 | agentReady | planned:TASK-12 restore drill | planned |
| NFR-6 | TASK-02, TASK-12 | agentReady, practiceReady | planned:TASK-12 telemetry assertions | partial |
| NFR-7 | TASK-08, TASK-09 | agentHealth, practiceHealth | planned:TASK-09 Helm lint/template/schema/package, Helm test and rollback verification | planned |
| NFR-8 | TASK-05, TASK-08, TASK-09, TASK-10 | agentHealth, practiceHealth, generatePracticeExercises | planned:TASK-10 Kind smoke workflow | planned |
| NFR-9 | TASK-09, TASK-11, TASK-12 | agentReady, practiceReady | planned:TASK-09 Helm rollback drill; planned:TASK-11 digest rollout verification | planned |

## Baseline verification

- `scripts/validate_contract_baseline.py` verifies requirement coverage, task references, operation IDs, implementation status annotations and local OpenAPI references.
- `tests/unit/test_contract_baseline.py` runs the validator in the normal test suite.
