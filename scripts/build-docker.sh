#!/usr/bin/env bash
# Generate uv.lock inside Docker build context.
# The lockfile is normally gitignored, so we generate it inside the builder image.
set -e

cd "$(dirname "$0")/.."

# Build args passed from docker-compose
TARGET="${1:-api}"

if [[ "$TARGET" == "api" ]]; then
    DOCKERFILE="apps/api/Dockerfile"
elif [[ "$TARGET" == "worker" ]]; then
    DOCKERFILE="services/ingestion/Dockerfile"
elif [[ "$TARGET" == "web" ]]; then
    DOCKERFILE="apps/web/Dockerfile"
else
    echo "Unknown target: $TARGET"
    exit 1
fi

# Build with legacy builder (no buildx cache issues)
DOCKER_BUILDKIT=0 docker compose -f infra/docker/docker-compose.yml build --no-cache "$TARGET"
