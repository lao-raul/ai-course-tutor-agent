variable "TAG" {
  default = "dev"
}

# Override with an approved mirror when the default registry is unavailable.
variable "PYTHON_IMAGE" {
  default = "docker.io/library/python:3.12-slim-bookworm@sha256:34386ef0cb081344d7ec1c103ba398e6e9f64e9ab3a1509accc92a4e24a07258"
}

variable "BUILD_VERSION" {
  default = "0.1.0-dev"
}

variable "BUILD_REVISION" {
  default = "unknown"
}

variable "BUILD_SOURCE" {
  default = "https://github.com/example/ai-course-tutor-agent"
}

group "default" {
  targets = ["agent-api", "practice-api", "practice-worker", "ingestion-worker", "web", "fake-llm"]
}

target "common" {
  context = "."
  # Kind/containerd cannot import BuildKit's local attestation manifest list.
  # CI publishes provenance separately; local images stay single-platform/loadable.
  provenance = false
  args = {
    PYTHON_IMAGE = PYTHON_IMAGE
    BUILD_VERSION = BUILD_VERSION
    BUILD_REVISION = BUILD_REVISION
    BUILD_SOURCE = BUILD_SOURCE
  }
}

target "agent-api" {
  inherits = ["common"]
  dockerfile = "apps/api/Dockerfile"
  tags = ["course-tutor-agent:${TAG}"]
}

target "practice-api" {
  inherits = ["common"]
  dockerfile = "apps/practice/Dockerfile"
  tags = ["course-tutor-practice:${TAG}"]
}

target "practice-worker" {
  inherits = ["common"]
  dockerfile = "services/practice_worker/Dockerfile"
  tags = ["course-tutor-practice-worker:${TAG}"]
}

target "ingestion-worker" {
  inherits = ["common"]
  dockerfile = "services/ingestion/Dockerfile"
  tags = ["course-tutor-worker:${TAG}"]
}

target "web" {
  inherits = ["common"]
  dockerfile = "apps/web/Dockerfile"
  tags = ["course-tutor-web:${TAG}"]
}

target "fake-llm" {
  inherits = ["common"]
  dockerfile = "infra/fake-llm/Dockerfile"
  tags = ["course-tutor-fake-llm:${TAG}"]
}
