# ADR-004: Two Backend Applications and Data Ownership

- **Status:** Accepted
- **Date:** 2026-09-09
- **Decision owners:** Project maintainers

## Context

The existing repository has one FastAPI application that owns course setup, ingestion administration and RAG chat. The product now also needs a separately deployable application for future random exercise generation. The exercise-generation requirements are not yet stable, while Kubernetes and CI/CD need a concrete workload boundary now.

Renaming the existing Python package would create broad mechanical churn without changing its runtime boundary. Allowing both applications to own course/content tables would introduce synchronization and authorization ambiguity.

## Decision

1. Keep the existing source path `apps/api` and Python package `course_tutor_api`. Name its process, image, Kubernetes Deployment and Service **Agent API** / `agent-api`.
2. Add `apps/practice` with package `course_tutor_practice`. Name its process, image, Deployment and Service **Practice API** / `practice-api`.
3. Agent API owns tenant, programme, course/course-run, content-version, source/chunk, session, memory, feedback and authorization data.
4. Practice API consumes versioned course/authorization/retrieval contracts. It must not import Agent API ORM models or internal route/application modules.
5. In v0.2 Practice API is a dummy service. Its generation endpoint authenticates and checks course scope when that shared capability exists, persists nothing and returns HTTP 501 with code `practice_generation_not_implemented`.
6. The ingestion worker is an Agent-owned supporting workload, not a third backend product app.
7. A single Helm chart packages Agent API, Practice API, ingestion worker and Web with independent enablement and scaling.

## Consequences

### Positive

- Kubernetes and CI/CD can verify two real deployment boundaries before practice-generation behavior is designed.
- Course authorization and content versioning have one system of record.
- The existing Agent prototype avoids a risky, low-value package rename.
- Practice generation can evolve or be replaced without coupling it to the Agent process.

### Costs

- Runtime/service names differ from the existing `apps/api` source directory.
- A versioned authorization/course contract is required between applications.
- Some current ingestion/retrieval imports from `course_tutor_api` must move behind shared/domain interfaces before clean service extraction.

## Alternatives rejected

- **One FastAPI process with two route groups:** rejected because it cannot prove independent packaging, scaling, failure isolation or deployment.
- **Duplicate course/content schema in Practice API:** rejected because it creates stale data, duplicated ACL logic and unclear deletion ownership.
- **Rename all existing Agent paths/packages immediately:** rejected because the mechanical migration is not required to establish the deployment boundary.

## Follow-up

- TASK-02 creates shared authentication/authorization interfaces.
- TASK-07 creates the Practice API dummy.
- TASK-08 packages independent images.
- TASK-09 declares both applications in Helm.
- A future ADR is required before Practice API persists exercise/attempt data.
