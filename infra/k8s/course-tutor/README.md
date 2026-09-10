# Course Tutor Helm chart

This is the only supported Kubernetes release package. The backend Deployment uses a
co-located Pod: `agent-api` and `practice-api` are separate containers with independent
ports, probes, resources and Services, but share one rollout and scaling unit.

## Local/CI install

Build and load the five application images, then run:

```bash
helm lint infra/k8s/course-tutor -f infra/k8s/course-tutor/values-ci.yaml
helm upgrade --install course-tutor infra/k8s/course-tutor \
  --namespace course-tutor --create-namespace \
  --values infra/k8s/course-tutor/values-ci.yaml \
  --atomic --wait --wait-for-jobs --timeout 10m
helm test course-tutor --namespace course-tutor --logs
```

Production supplies immutable image digests, external service endpoints and an
existing Secret. Course material is mounted from an existing read-only PVC; for SMB,
provision that PVC with the cluster's SMB CSI driver and keep credentials in a Secret.
The example values contain no credentials.
