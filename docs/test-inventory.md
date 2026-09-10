# Test inventory and requirement coverage

The automated suite is split by dependency level. All test content is generated or
synthetic; no suite reads the Leeds NAS or calls the LAN LM Studio endpoint.

| Requirement / regression | Suite | Primary tests | CI gate |
|---|---|---|---|
| Health, configuration, dependency lifecycle | Unit | `tests/unit/test_health.py`, `tests/unit/test_dependency_lifecycle.py` | `quality` |
| Agent and Practice OpenAPI contracts | Unit / contract | `tests/unit/test_contract_baseline.py`, `apps/practice/tests/` | `quality` |
| Tenant/course ACL and authentication | Unit / integration | `tests/unit/test_retrieval_acl.py`, `tests/integration/security/` | `quality`, `integration` |
| Citation mapping and ordered SSE protocol | Integration | `tests/integration/chat/` | `quality`, `integration` |
| Repeated ingestion and version readiness | Integration | `tests/integration/test_ingestion_idempotency.py`, `tests/integration/ingestion/` | `integration` |
| Safe destructive database setup | Integration harness | `tests/support/postgres.py` | `integration` |
| Generated course: ingest, embed, publish, list, ask, cite | E2E | `tests/e2e/test_grounded_course_flow.py` | `integration` |
| Retrieval quality and abstention | Benchmark | `tests/retrieval_benchmark.py` | `integration` |
| Helm install and two-container backend Pod | Deployment smoke | `scripts/kind-smoke-test.sh`, Helm test Pod | `package-and-deploy` |

The destructive database guard requires the `course_tutor_test_` database-name prefix.
Before `DROP SCHEMA`, a non-empty database must also contain a matching
`_course_tutor_test_marker`; only a newly created empty test database is allowed to
bootstrap that marker. `TEST_POSTGRES_DSN` is mandatory for PostgreSQL suites.

The RAG quality gate emits `build/reports/rag-metrics.json` and currently requires:

- Recall@5 >= 0.85
- MRR >= 0.80
- citation precision >= 0.95
- abstention F1 >= 0.90
- p95 retrieval latency <= 250 ms for the deterministic in-memory benchmark

JUnit and RAG JSON reports are uploaded by CI. Run the full disposable integration
environment with `scripts/run-integration-tests.sh`; the cleanup trap always removes
its containers and volumes.
