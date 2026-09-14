# Course bootstrap and grounded-chat runbook

Use this only after the local-real Helm release and `local-real-preflight.sh` pass.
The bootstrap maps one explicit module directory to stable programme/course/run IDs;
it never guesses ownership by scanning arbitrary NAS names.

## Configure and reach the Agent API

```bash
mkdir -p .local
cp docs/examples/leeds-course.example.yaml .local/leeds-course.yaml
kubectl -n course-tutor port-forward service/course-tutor-agent 8000:8000
```

In another terminal, set the same local bearer token used by the runtime Secret and
edit `.local/leeds-course.yaml`. `course.source_path` is the path *inside* the
container, for example `/data/content/COMP1234`; never put the host or SMB path there.
The selected directory and metadata are explicit operator input.

## Register idempotently

```bash
export COURSE_TUTOR_AUTH_TOKEN='value-from-your-local-secret-manager'
scripts/course-bootstrap.sh --config .local/leeds-course.yaml
scripts/course-bootstrap.sh --config .local/leeds-course.yaml
```

Both runs return the same programme, course, course-run and SourceRoot IDs. If a code
already exists with a different name, run key, source path or scan interval, the
command fails rather than silently changing ownership or creating duplicates.

## Ingest, inspect and publish explicitly

```bash
scripts/course-bootstrap.sh --config .local/leeds-course.yaml --ingest --wait
scripts/course-bootstrap.sh --config .local/leeds-course.yaml \
  --ingest --wait --retry-failed
scripts/course-bootstrap.sh --config .local/leeds-course.yaml --publish
```

`--ingest --wait` exits only when the immutable version is READY, the source is
unchanged, the job is dead-lettered, or the bounded timeout expires. It prints IDs
and status but not the host source path, token or source content. `--publish` is a
separate action and publishes the newest READY version; registration and ingestion
never switch the active version implicitly.

Useful inspection calls are:

```bash
curl -H "Authorization: Bearer $COURSE_TUTOR_AUTH_TOKEN" \
  http://127.0.0.1:8000/v1/admin/courses/COURSE_ID/versions
curl -H "Authorization: Bearer $COURSE_TUTOR_AUTH_TOKEN" \
  'http://127.0.0.1:8000/v1/admin/courses/COURSE_ID/sources?version_id=VERSION_ID'
curl -X POST -H "Authorization: Bearer $COURSE_TUTOR_AUTH_TOKEN" \
  http://127.0.0.1:8000/v1/admin/ingestions/JOB_ID/retry
curl -X POST -H "Authorization: Bearer $COURSE_TUTOR_AUTH_TOKEN" \
  http://127.0.0.1:8000/v1/admin/courses/COURSE_ID/versions/VERSION_ID/rollback
```

Rollback requires the supplied version to be active and preserves the prior
published version. Database records are not automatically removed; deleting shared
course data is intentionally outside this bootstrap command.

## Verify API and browser behavior

Set `e2e.in_scope_question` to something answered by the selected module, then run:

```bash
scripts/local-course-e2e.sh --config .local/leeds-course.yaml
kubectl -n course-tutor port-forward service/course-tutor-web 8080:80
```

The automated check requires the course in `GET /v1/courses`, an active published
version, streamed token/citation/done events, a citation path belonging to that exact
version, and abstention for the configured unrelated question. Open
`http://127.0.0.1:8080`, select the course, submit the same in-scope question and
record the visible citation. A dated verification record must contain only redacted
endpoint/model information and generated IDs—not learner data, tokens, paths or
course text.
