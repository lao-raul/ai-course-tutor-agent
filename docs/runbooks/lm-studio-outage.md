# LM Studio outage runbook

1. Confirm `course_tutor_dependency_up{dependency="llm"}` and
   `course_tutor_llm_circuit_open`; correlate with Agent logs using the response
   `X-Correlation-ID` without logging prompt content.
2. Check network reachability and `/v1/models` from the Agent namespace. Confirm the
   configured chat and embedding model IDs are loaded.
3. Do not restart healthy Agent pods repeatedly. Liveness should remain green;
   readiness is degraded and requests fail within the configured timeout/retry budget.
4. Restore LM Studio or switch an approved compatible endpoint through a reviewed Helm
   values change. Never weaken model/dimension validation to regain readiness.
5. Verify `/readyz`, one cited or explicitly abstained synthetic chat, circuit closure,
   and error-budget recovery. Record start/end time and affected release revision.

If the outage threatens the monthly 99.5% SLO, stop releases and invoke the secondary
inference endpoint plan. Production cannot claim higher availability until that endpoint
has passed the same embedding-dimension and RAG quality gates.
