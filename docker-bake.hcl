variable "TAG" {
  default = "dev"
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
  targets = ["agent-api", "practice-api", "ingestion-worker", "web", "fake-llm"]
}

target "common" {
  context = "."
  # Kind/containerd cannot import BuildKit's local attestation manifest list.
  # CI publishes provenance separately; local images stay single-platform/loadable.
  provenance = false
  args = {
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
