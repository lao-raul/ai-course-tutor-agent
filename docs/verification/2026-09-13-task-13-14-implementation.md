# TASK-13/14 local-real completion verification — 2026-09-13

This record intentionally omits credentials, course paths, course names/content and
the full private LAN endpoint.

## Passed

- Helm lint and template passed for both CI and placeholder-only local-real profiles.
- The chart rejected simultaneous real course content and fake LLM enablement.
- CI-profile Helm upgrade reached revision 15 and the hook test completed Succeeded.
- The backend Pod contained exactly `agent-api` and `practice-api`; generated fixture
  ingestion, explicit publication and ordered token/citation/done SSE passed.
- Host-side LM Studio model discovery passed against `http://192.168.x.x:1234/v1`.
- The selected embedding provider returned dimension 1024.
- One bounded chat request returned successfully.
- Python lint/format/type checks, 86 unit tests, 23 disposable integration/E2E tests,
  2 Web tests and the production Web build passed.
- RAG gates: recall@5, MRR, citation precision, abstention precision/recall/F1 all 1.0.

## Live acceptance passed

- The reconnected SMB mount returned a stable course inventory. A dedicated
  `course-tutor-real` Kind cluster mounted it through the external
  `course-tutor-content` PVC, which reached `Bound`.
- Helm release `course-tutor` reached `deployed`, revision 2, in namespace
  `course-tutor`. The backend Pod contained the Agent and Practice containers; Worker
  and Web ran as supporting workloads.
- Pre-install and final post-install preflight passed. Agent and Worker had read-only
  course access, write attempts failed, Practice and Web had no course mount, and the
  fake LLM workload was absent.
- In-cluster LM Studio checks passed against `http://192.168.x.x:1234/v1`: both models
  were discovered, embedding width was 1024 and bounded chat completed.
- Running course bootstrap twice returned identical programme, course, run and
  SourceRoot identities.
- The real scan discovered 19 supported files and indexed 844 chunks. Two encrypted
  PDFs were retained as failed extractions; they did not block the usable source set.
  Publication remained explicit and selected the READY immutable version.
- An unchanged follow-up scan reported 19 unchanged files, zero new chunks and no new
  content version.
- API E2E passed with two citations belonging to the active version and an explicit
  abstention event for an unrelated weather question.
- Browser E2E displayed the mapped course, enabled the chat input, streamed a grounded
  answer and showed two Unit 1 slide citations.

## Defects found and corrected during live validation

- Embedding calls and database chunk reads are now independently bounded to 32-item
  pages, preventing textbook-sized versions from being loaded into Worker memory.
- The local-real Worker recommendation is 2 GiB because extraction of image-heavy
  textbooks exceeded the conservative 1 GiB default.
- Manual ingestion now joins an already pending scheduled/manual scan, and a matching
  BUILDING snapshot prevents a duplicate immutable version.
- Grounding uses a low score floor plus lexical support below the high-confidence
  semantic threshold; this preserves short valid questions while rejecting unrelated
  high-baseline embedding matches.
- The pinned MinIO image now uses the verified Quay location because the same tag was
  no longer pullable from Docker Hub.

## Final regression evidence

- 84 unit tests passed.
- 23 disposable integration/E2E tests passed.
- Ruff, formatting and mypy (37 backend source files) passed.
- RAG recall@5, MRR, citation precision and abstention precision/recall/F1 were all
  1.0.
- Helm lint/template and both Docker Compose configurations passed.
