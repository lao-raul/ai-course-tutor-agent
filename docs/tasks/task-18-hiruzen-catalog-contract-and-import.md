# TASK-18 — Hiruzen Catalog Contract and ChinaTextbook Import

**Status:** complete (2026-10-07)
**Priority:** P0  
**Depends on:** TASK-17

## Goal

Create the Agent-owned catalog used by Hiruzen and stage ChinaTextbook metadata from
the read-only NAS without exposing filesystem paths or creating a second RAG/content
owner in the Practice service.

## Scope

- Add tenant-scoped Category, Publisher, Book and book/content/course binding models.
- Add immutable catalog import batches and reviewable candidates.
- Scan ChinaTextbook PDF metadata from configurable read-only roots, initially the
  primary-school English FLTRP family.
- Parse education level, subject, series, publisher, start grade, editor, grade and
  term while quarantining ambiguous layouts.
- Generate stable identity from normalized metadata rather than absolute mount paths.
- Add approval/import workflow and Agent catalog read contracts.
- On approval, create one Book and system-managed Course/CourseRun, then queue existing
  ingestion; publish visibility still requires explicit ContentVersion publication.
- Add server-derived `tenant_authenticated` authorization for published system textbook
  CourseRuns without weakening membership ACLs on normal courses.
- Implement the Hiruzen catalog facade strictly through the Agent HTTP contract.

## Deliverable artifacts

| Artifact | Repository path | Status |
|---|---|---|
| Catalog DTOs and closed enums | `packages/contracts/src/course_tutor_contracts/{catalog,domain,enums}.py` | implemented |
| Agent Catalog ORM model | `apps/api/src/course_tutor_api/db/models.py` | implemented |
| Catalog database migration | `apps/api/alembic/versions/{b6a4d2c8e901_hiruzen_catalog_staging,c7e13a09d4f2_course_run_access_policy}.py` | implemented |
| ChinaTextbook scanner/staging importer | `services/ingestion/src/course_tutor_ingestion/china_textbook_catalog.py` | implemented |
| Agent catalog admin/read routes | `apps/api/src/course_tutor_api/routes/{catalog_admin,catalog}.py` | implemented |
| Hiruzen Agent client and catalog facade | `apps/practice/src/course_tutor_practice/{adapters/agent_client.py,routes/catalog.py}` | implemented |
| Versioned Agent/Practice contracts | `packages/contracts/openapi/{agent-api,practice-api}.v1.json` | implemented |
| Parser/importer and API contract tests | `tests/{unit/ingestion,integration/catalog}/`, `apps/practice/tests/` | implemented |
| One-command local build/deploy helper | `scripts/deploy-hiruzen-local.sh` | implemented |
| Completion evidence | `docs/verification/2026-10-07-task-18.md` | implemented |

## Acceptance criteria

- **AC-18.1:** Re-scanning an unchanged selection produces the same snapshot and no duplicate
  import batch. **Observable check:** call `POST /v1/admin/catalog/imports` twice with the same
  `Idempotency-Key`; both responses must have the same `import_id`. Re-run with a new key after
  the first scan reaches `staged`; `GET /v1/admin/catalog/imports/{import_id}` must report the
  same `batch_id` for unchanged files.
- **AC-18.2:** All 36 observed FLTRP pilot PDFs are parsed into reviewable candidates without an
  absolute NAS path in any public response. **Observable check:** the staged job reports
  `candidate_count: 36`, and `GET /v1/admin/catalog/imports/{import_id}/candidates` returns 36
  entries whose public JSON contains neither `/Volumes/`, `/var/services/` nor `/data/content`.
- **AC-18.3:** Ambiguous metadata remains `needs_review` and cannot become searchable implicitly.
  **Observable check:** approving a `needs_review` candidate returns HTTP 409; after an explicit
  metadata correction through `PATCH .../candidates/{candidate_id}`, it becomes `staged` but is
  still absent from catalog search until approval, ingestion and publication complete. The pilot
  set currently has no ambiguous candidate, so the HTTP-409 branch is also retained as an
  integration-test acceptance check.
- **AC-18.4:** Published catalog queries are tenant/authorization scoped and support the filters in
  HFR-CAT-2 with deterministic pagination. **Observable check:** Agent
  `GET /v1/catalog/books` and Hiruzen `GET /v1/practice/catalog/books` return the same published
  book for `education_level=primary`, `subject=英语`, `publisher=外研社`; `limit=1` returns a stable
  `next_cursor` when more than one match exists.
- **AC-18.5:** Hiruzen has no NAS mount and imports no Agent ORM or route module.
  **Observable check:** the deployed Pod shows `course-content` only on `agent-api`; the
  `practice-api` container has no such volume mount. The dependency-boundary validator verifies
  source imports.
- **AC-18.6:** Migration upgrade/downgrade, parser/importer tests, API contract tests and
  baseline validators pass. The commands in **Automated acceptance** below must exit zero.
- **AC-18.7:** Approved candidates create idempotent Book/CourseRun bindings and queue
  ingestion, while only an explicitly published ContentVersion makes the Book searchable.
  **Observable check:** candidate approval returns `book_id`, `course_id`, `course_run_id` and
  `ingestion_job_id`; the book is absent before `POST .../publish` and present through both Agent
  and Hiruzen catalog APIs afterwards. Repeating approval returns the same IDs.
- **AC-18.8:** Any authenticated user in the tenant can access a published system
  textbook CourseRun, while cross-tenant and non-system course access still fails closed.
  **Observable check:** the local authenticated user, without explicit course enrollment, can
  read the published book/course through Hiruzen. Cross-tenant denial and normal-course denial
  require isolated principals and are verified by the integration suite.

### Actual-environment build and deployment

These commands exercise the AC against the macOS NAS mount confirmed for ChinaTextbook. The Kind
cluster maps `/Volumes/home/ChinaTextbook` read-only to `/data/content` inside Agent and worker;
API payloads must use that container path, never the host path.

Prerequisites: Docker Desktop with buildx, `kind`, `kubectl`, Helm 3, `jq`, `uv`, a reachable LM
Studio OpenAI-compatible endpoint, and loaded chat/embedding models.

The recommended acceptance path is the one-command helper. It creates or reuses the dedicated
`course-tutor-hiruzen` cluster, configures the read-only PV/PVC and Secret, builds and loads four
application images, runs preflight, installs the Helm release, and checks both API containers:

```bash
export COURSE_TUTOR_AUTH_TOKEN='replace-with-local-token'
export COURSE_TUTOR_MINIO_SECRET='replace-with-random-secret'

scripts/deploy-hiruzen-local.sh
```

Use `scripts/deploy-hiruzen-local.sh --help` for cluster/path/value overrides. A subsequent deploy
can reuse a previously built tag with `--tag TAG --skip-build`. The expanded commands below are
the manual fallback and troubleshooting reference. The helper defaults to the currently verified
`qwen/qwen3.6-35b-a3b` chat model, `text-embedding-qwen3-embedding-0.6b` embedding model and
dimension 1024, and validates the IDs and dimension against LM Studio before building.

```bash
# Use a dedicated cluster because Kind host mounts are immutable after cluster creation.
# This also preserves an existing course-tutor-real cluster used by Leeds content.
export KIND_CLUSTER=course-tutor-hiruzen
scripts/local-real-kind-setup.sh \
  --host-path "/Volumes/home/ChinaTextbook" \
  --cluster "$KIND_CLUSTER"
kubectl config use-context "kind-$KIND_CLUSTER"

# Use a unique image tag so Kind and Helm cannot reuse stale local images.
export IMAGE_TAG="task18-$(git rev-parse --short HEAD)-$(date +%H%M%S)"
TAG="$IMAGE_TAG" scripts/build-docker.sh agent-api practice-api ingestion-worker web
kind load docker-image --name "$KIND_CLUSTER" \
  "course-tutor-agent:$IMAGE_TAG" \
  "course-tutor-practice:$IMAGE_TAG" \
  "course-tutor-worker:$IMAGE_TAG" \
  "course-tutor-web:$IMAGE_TAG"
```

Create `course-tutor-local-runtime` and `.local/course-tutor.values.yaml` as described in the root
README. Confirm that `courseContent.mountPath` is `/data/content`, `fakeLlm.enabled` is false and
the real LM Studio model IDs/dimension are configured, then install:

```bash
export LLM_BASE_URL='http://192.168.50.146:1234/v1'
export LLM_CHAT_MODEL='qwen/qwen3.6-35b-a3b'
export LLM_EMBEDDING_MODEL='text-embedding-qwen3-embedding-0.6b'
export LLM_EMBEDDING_DIMENSION=1024
export PREFLIGHT_IMAGE="course-tutor-agent:$IMAGE_TAG"

scripts/local-real-preflight.sh
helm lint infra/k8s/course-tutor \
  -f infra/k8s/course-tutor/values-local-real.example.yaml \
  -f .local/course-tutor.values.yaml
helm upgrade --install course-tutor infra/k8s/course-tutor \
  --namespace course-tutor --create-namespace \
  -f infra/k8s/course-tutor/values-local-real.example.yaml \
  -f .local/course-tutor.values.yaml \
  --set-string backend.agent.image.tag="$IMAGE_TAG" \
  --set-string backend.practice.image.tag="$IMAGE_TAG" \
  --set-string worker.image.tag="$IMAGE_TAG" \
  --set-string web.image.tag="$IMAGE_TAG" \
  --atomic --wait --wait-for-jobs --timeout 10m

helm status course-tutor -n course-tutor
kubectl get pods -n course-tutor
scripts/local-real-preflight.sh
```

The deployment portion passes when Helm reports `deployed`, all workloads are Ready, the
preflight reports a readable but non-writable NAS volume, and it confirms that Practice has no
course-content mount.

### Actual-environment function-call test

Open two long-running port forwards in separate terminals:

```bash
kubectl -n course-tutor port-forward service/course-tutor-agent 18000:8000
kubectl -n course-tutor port-forward service/course-tutor-practice 18001:8001
```

Set the same local bearer token that was stored in `course-tutor-local-runtime`:

```bash
export AGENT_URL=http://127.0.0.1:18000
export PRACTICE_URL=http://127.0.0.1:18001
export COURSE_TUTOR_AUTH_TOKEN='replace-with-local-token'
export AUTH_HEADER="Authorization: Bearer $COURSE_TUTOR_AUTH_TOKEN"

curl -fsS "$AGENT_URL/readyz" | jq
curl -fsS "$PRACTICE_URL/readyz" | jq
```

Create a one-time source-root anchor and retain its response for repeatable scans. This normal
course is only a configuration anchor; approving a candidate creates the system-owned textbook
CourseRun required by AC-18.7/18.8.

```bash
mkdir -p .local
PROGRAMME_ID="$(curl -fsS -H "$AUTH_HEADER" \
  "$AGENT_URL/v1/admin/programmes?code=CHINA-TEXTBOOK-IMPORT" \
  | jq -r '.[0].programme_id // empty')"
if [ -z "$PROGRAMME_ID" ]; then
  PROGRAMME_ID="$(curl -fsS -X POST -H "$AUTH_HEADER" \
    -H 'Content-Type: application/json' \
    "$AGENT_URL/v1/admin/programmes" \
    -d '{"code":"CHINA-TEXTBOOK-IMPORT","name":"ChinaTextbook import source"}' \
    | jq -r .programme_id)"
fi

curl -fsS -X POST -H "$AUTH_HEADER" -H 'Content-Type: application/json' \
  "$AGENT_URL/v1/admin/courses" \
  -d "{\"programme_id\":\"$PROGRAMME_ID\",\"code\":\"CHINA-TEXTBOOK-SOURCE\",\"name\":\"ChinaTextbook source root\",\"level\":\"primary\",\"run_key\":\"catalog-source\",\"source_path\":\"/data/content\",\"scan_interval_seconds\":900,\"automatic_ingestion_enabled\":false}" \
  | tee .local/china-textbook-source.json | jq
export SOURCE_ROOT_ID="$(jq -r .source_root_id .local/china-textbook-source.json)"
```

The course registration is intentionally one-time because `code` is unique. On later runs, skip
the POST and load `SOURCE_ROOT_ID` from `.local/china-textbook-source.json`.

Queue and observe the pilot scan:

```bash
curl -fsS -X POST -H "$AUTH_HEADER" -H 'Content-Type: application/json' \
  -H 'Idempotency-Key: fltrp-primary-english-v1' \
  "$AGENT_URL/v1/admin/catalog/imports" \
  -d "{\"source_root_id\":\"$SOURCE_ROOT_ID\",\"prefix\":\"小学/英语\",\"series_contains\":\"外研社\"}" \
  | tee .local/catalog-import.json | jq
export IMPORT_ID="$(jq -r .import_id .local/catalog-import.json)"

# Repeat until status is staged; candidate_count must be 36 for the confirmed pilot tree.
curl -fsS -H "$AUTH_HEADER" \
  "$AGENT_URL/v1/admin/catalog/imports/$IMPORT_ID" | jq
curl -fsS -H "$AUTH_HEADER" \
  "$AGENT_URL/v1/admin/catalog/imports/$IMPORT_ID/candidates" \
  | tee .local/catalog-candidates.json | jq 'length'

# Public candidate responses must not leak any host/container path.
if grep -E '/Volumes/|/var/services/|/data/content' .local/catalog-candidates.json; then
  echo 'FAIL: catalog response leaked a filesystem path' >&2
  exit 1
fi
```

Approve exactly one staged book and observe the existing ingestion/publication lifecycle:

```bash
export CANDIDATE_ID="$(jq -r '[.[] | select(.status == "staged")][0].id' \
  .local/catalog-candidates.json)"
curl -fsS -X POST -H "$AUTH_HEADER" \
  "$AGENT_URL/v1/admin/catalog/imports/$IMPORT_ID/candidates/$CANDIDATE_ID/approve" \
  | tee .local/catalog-approval.json | jq

export BOOK_ID="$(jq -r .book_id .local/catalog-approval.json)"
export COURSE_ID="$(jq -r .course_id .local/catalog-approval.json)"
export INGESTION_JOB_ID="$(jq -r .ingestion_job_id .local/catalog-approval.json)"

# Before publication, this exact book must not be visible.
curl -fsS -H "$AUTH_HEADER" "$AGENT_URL/v1/catalog/books?limit=100" \
  | jq --arg id "$BOOK_ID" '[.items[] | select(.id == $id)] | length'

# Repeat until version_status is READY; failed/dead_lettered is an AC failure.
curl -fsS -H "$AUTH_HEADER" \
  "$AGENT_URL/v1/admin/ingestions/$INGESTION_JOB_ID" \
  | tee .local/catalog-ingestion.json | jq
export VERSION_ID="$(jq -r .version_id .local/catalog-ingestion.json)"

curl -fsS -X POST -H "$AUTH_HEADER" \
  "$AGENT_URL/v1/admin/courses/$COURSE_ID/versions/$VERSION_ID/publish" | jq

# Agent and Hiruzen must now expose the same published book.
curl -fsS -H "$AUTH_HEADER" \
  "$AGENT_URL/v1/catalog/books?education_level=primary&subject=%E8%8B%B1%E8%AF%AD&publisher=%E5%A4%96%E7%A0%94%E7%A4%BE&limit=100" \
  | jq --arg id "$BOOK_ID" '[.items[] | select(.id == $id)] | length'
curl -fsS -H "$AUTH_HEADER" \
  "$PRACTICE_URL/v1/practice/catalog/books?education_level=primary&subject=%E8%8B%B1%E8%AF%AD&publisher=%E5%A4%96%E7%A0%94%E7%A4%BE&limit=100" \
  | jq --arg id "$BOOK_ID" '[.items[] | select(.id == $id)] | length'
curl -fsS -H "$AUTH_HEADER" \
  "$PRACTICE_URL/v1/practice/catalog/books/$BOOK_ID" | jq
```

The pre-publication count must be `0`; both post-publication counts must be `1`. The Hiruzen book
detail must contain the published `content_version_id` and a `tenant_authenticated` CourseRun.

### Browser-observable operations

TASK-18 does not own a catalog page; that learner UI is a TASK-22 deliverable. Until TASK-22 is
complete, the same function calls can be invoked and inspected through FastAPI's interactive API
pages after using **Authorize** with the bearer token:

- Agent admin/catalog operations: <http://127.0.0.1:18000/docs>
- Hiruzen catalog facade: <http://127.0.0.1:18001/docs>

The existing Web page on port 18080 is therefore not an acceptance surface for TASK-18.

### Automated acceptance

Run the focused contract and flow tests before the actual-environment test:

```bash
uv sync --extra dev --frozen
uv run pytest \
  tests/unit/ingestion/test_china_textbook_catalog.py \
  tests/integration/catalog \
  apps/practice/tests/test_app.py \
  tests/unit/test_contracts.py -q
uv run python scripts/validate_hiruzen_baseline.py
uv run ruff check apps/api apps/practice services/ingestion packages/contracts tests
uv run mypy apps/api/src apps/practice/src services/ingestion/src packages/contracts/src
helm lint infra/k8s/course-tutor -f infra/k8s/course-tutor/values-ci.yaml
```

## Independent delivery boundary

TASK-18 owns Agent catalog/import contracts and only the Hiruzen catalog facade. It
must not add Practice persistence or generation behavior. Its versioned Book/CourseRun
DTOs are the frozen input contract for TASK-19 and TASK-20.

## Verification

Acceptance requires both the **Automated acceptance** command set and the observable deployment/API
checks above. Record actual IDs, status transitions and any failure diagnostics in the completion
evidence; do not treat a successful image build alone as functional acceptance.

## Progress

- Catalog scans are queued through the transactional outbox and executed only by the
  ingestion worker that owns the read-only NAS mount.
- Candidate correction, rejection, individual approval and batch approval are implemented.
  Approval idempotently creates Book/system CourseRun bindings and a single-file ingestion job.
- Published catalog reads, cursor/filter behavior, Hiruzen's HTTP-only facade and
  server-derived `tenant_authenticated` authorization are implemented.
- A read-only real-NAS scan found exactly 36 FLTRP pilot PDFs across the four expected
  series with zero parser review issues; snapshot prefix `76c4ca4eb0616d04`.
- Migration round trip, unit, integration/E2E, Ruff, mypy, Helm and both specification
  baseline validators pass. Evidence is recorded in
  `docs/verification/2026-10-07-task-18.md`.
