# ---- Ingestion Worker Docker image ----
FROM python:3.12-slim AS base

WORKDIR /app

COPY --from=ghcr.io/astral-sh/uv:latest /uv /usr/local/bin/uv

RUN apt-get update && apt-get install -y --no-install-recommends \
    libpq-dev gcc \
    && rm -rf /var/lib/apt/lists/*

COPY pyproject.toml packages/ apps/api/pyproject.toml services/*/pyproject.toml ./
RUN uv sync --frozen --no-install-project --all-packages --extra dev

FROM base AS worker-build

COPY apps/api/src ./apps/api/src
COPY packages/contracts/src ./packages/contracts/src
COPY packages/shared/src ./packages/shared/src
COPY services/ingestion/src ./services/ingestion/src
COPY services/retrieval/src ./services/retrieval/src

RUN uv sync --frozen --all-packages --extra dev

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

# Wait for postgres + qdrant before starting
ENTRYPOINT ["/bin/bash", "-c", "\
    echo 'Waiting for postgres...' && \
    python -c 'import socket,os; s=socket.socket(); s.connect((os.environ[\"POSTGRES_HOST\"],int(os.environ[\"POSTGRES_PORT\"]))); s.close()' && \
    echo 'Starting ingestion worker...' && \
    python -m course_tutor_ingestion"]
