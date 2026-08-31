# ---- API Docker image ----
FROM python:3.12-slim AS base

WORKDIR /app

RUN pip install --no-cache-dir uv

RUN apt-get update && apt-get install -y --no-install-recommends \
    libpq-dev gcc \
    && rm -rf /var/lib/apt/lists/*

# Copy all source — needed so uv lock can resolve every workspace member
COPY apps/api/src ./apps/api/src
COPY packages/contracts/src ./packages/contracts/src
COPY packages/shared/src ./packages/shared/src
COPY services/ingestion/src ./services/ingestion/src
COPY services/retrieval/src ./services/retrieval/src

# Copy per-package manifests (no root pyproject.toml — avoids workspace member
# resolution in base stage where it would try to install all members)
COPY apps/api/pyproject.toml ./apps/api/pyproject.toml
COPY packages/contracts/pyproject.toml ./packages/contracts/pyproject.toml
COPY packages/shared/pyproject.toml ./packages/shared/pyproject.toml
COPY services/ingestion/pyproject.toml ./services/ingestion/pyproject.toml
COPY services/retrieval/pyproject.toml ./services/retrieval/pyproject.toml
COPY pyproject.toml ./pyproject.toml

# ---- API build stage ----
FROM base AS api-build

# Copy lockfile so we use the committed reproducible lock
COPY uv.lock ./uv.lock

# uv lock: generate a lockfile from all workspace members (source already in base)
# uv sync: install using the lockfile
RUN uv lock && uv sync --frozen --no-install-project --extra dev

# Copy source on top of whatever uv installed (overwrites stubs)
COPY apps/api/src ./apps/api/src
COPY apps/api/alembic ./apps/api/alembic
COPY packages/contracts/src ./packages/contracts/src
COPY packages/shared/src ./packages/shared/src
COPY services/ingestion/src ./services/ingestion/src
COPY services/retrieval/src ./services/retrieval/src

# Re-install api in editable mode to pick up src/ changes
RUN uv sync --frozen --extra dev

# ---- Runtime stage ----
FROM base AS runtime

ENV PYTHONUNBUFFERED=1
ENV PYTHONDONTWRITEBYTECODE=1

COPY --from=api-build /app/.venv /app/.venv
COPY --from=api-build /app/apps/api/src /app/apps/api/src
COPY --from=api-build /app/apps/api/alembic /app/apps/api/alembic
COPY --from=api-build /app/packages/contracts/src /app/packages/contracts/src
COPY --from=api-build /app/packages/shared/src /app/packages/shared/src
COPY --from=api-build /app/services/retrieval/src /app/services/retrieval/src

ENV PATH="/app/.venv/bin:$PATH"

RUN useradd --create-home --shell /bin/bash appuser
USER appuser

EXPOSE 8000

ENTRYPOINT ["/bin/bash", "-c", "\
    echo 'Waiting for postgres...' && \
    python -c 'import socket,os; s=socket.socket(); s.connect((os.environ[\"POSTGRES_HOST\"],int(os.environ[\"POSTGRES_PORT\"]))); s.close()' && \
    echo 'Running migrations...' && \
    alembic -c apps/api/alembic.ini upgrade head && \
    echo 'Starting API...' && \
    uvicorn 'course_tutor_api:create_app()' --factory --host 0.0.0.0 --port 8000 \
"]
