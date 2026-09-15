# Service-level objectives

These objectives apply to a production Course Tutor environment and are measured over
a rolling 30-day window. Synthetic tests and planned maintenance are reported
separately; they are not silently removed from the data.

| User outcome | SLI | SLO | Alert signal |
|---|---|---:|---|
| Agent chat is available | authenticated chat streams ending in `done` or explicit `abstained`, divided by accepted chat requests | 99.5% | 10-minute 1% server-error burn; dependency readiness |
| Agent response begins promptly | time from accepted request to first SSE token/abstention | P50 < 3 s, P95 < 8 s on the approved LAN baseline | LLM/retrieval histograms and scheduled synthetic chat |
| Practice API is available | successful health, readiness and capabilities requests | 99.5% | HTTP error ratio and Kubernetes readiness |
| Course changes become reviewable | successful scan reaches READY after source change | 95% within 30 minutes; no dead-letter older than 15 minutes | outbox pending/dead-letter depth |
| Memory deletion completes | tombstone immediately blocks recall and purge removes derived data | 99% purge within 15 minutes, 100% within 24 hours | memory operation audit plus purge queue depth |

Agent availability intentionally includes the configured LM Studio/compatible inference
service. A single workstation therefore remains inside the 99.5% failure budget; a
second compatible inference endpoint and provider-level failover are prerequisites for
a stronger SLO. Liveness remains healthy during a dependency outage, while readiness,
`course_tutor_dependency_up` and the user-safe chat error identify degradation.

Metrics use only bounded labels (`service`, route template, method, status class,
dependency, operation, outcome and stable queue topic). Tenant, course, user, source
path, prompt, memory content and correlation ID are never metric labels.
