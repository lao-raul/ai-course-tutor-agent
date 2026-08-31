# ---- Ingestion Worker Docker image ----
FROM python:3.12-slim AS base

WORKDIR /app

RUN pip install --no-cache-dir uv

RUN apt-get update && apt-get install -y --no-install-recommends \
    libpq-dev gcc \
    && rm -rf /var/lib/apt/lists/*

# Copy all source + per-package pyproject.toml + root workspace manifest + lockfile
COPY apps/api/src ./apps/api/src
COPY packages/contracts/src ./packages/contracts/src
COPY packages/shared/src ./packages/shared/src
COPY services/ingestion/src ./services/ingestion/src
COPY services/retrieval/src ./services/retrieval/src
COPY apps/api/pyproject.toml ./apps/api/pyproject.toml
COPY packages/contracts/pyproject.toml ./packages/contracts/pyproject.toml
COPY packages/shared/pyproject.toml ./packages/shared/pyproject.toml
COPY services/ingestion/pyproject.toml ./services/ingestion/pyproject.toml
COPY services/retrieval/pyproject.toml ./services/retrieval/pyproject.toml
COPY pyproject.toml ./pyproject.toml
COPY uv.lock ./uv.lock

# Sync using existing lockfile
RUN uv sync --frozen --no-install-project --extra dev

FROM base AS worker-build

COPY apps/api/src ./apps/api/src
COPY packages/contracts/src ./packages/contracts/src
COPY packages/shared/src ./packages/shared/src
COPY services/ingestion/src ./services/ingestion/src
COPY services/retrieval/src ./services/retrieval/src
COPY uv.lock ./uv.lock

RUN uv sync --frozen --no-install-project --extra dev

# Runtime
FROM base AS runtime

ENV PYTHONUNBUFFERED=1
ENV PYTHONDONTWRITEBYTECODE=1

COPY --from=worker-build /app/.venv /app/.venv
COPY --from=worker-build /app/apps/api/src /app/apps/api/src
COPY --from=worker-build /app/packages/contracts/src /app/packages/contracts/src
COPY --from=worker-build /app/packages/shared/src /app/packages/shared/src
COPY --from=worker-build /app/services/ingestion/src /app/services/ingestion/src
COPY --from=worker-build /app/services/retrieval/src /app/services/retrieval/src

ENV PATH="/app/.venv/bin:$PATH"

# Wait for postgres before starting
ENTRYPOINT ["/bin/bash", "-c", "\
    echo 'Waiting for postgres...' && \
    python -c 'import socket,os; s=socket.socket(); s.connect((os.environ[\"POSTGRES_HOST\"],int(os.environ[\"POSTGRES_PORT\"]))); s.close()' && \
    echo 'Starting ingestion worker...' && \
    python -m course_tutor_ingestion"]
