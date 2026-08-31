# ---- API Docker image ----
FROM python:3.12-slim AS base

WORKDIR /app

# Install uv
COPY --from=ghcr.io/astral-sh/uv:latest /uv /usr/local/bin/uv

# Install system deps for asyncpg, cryptography
RUN apt-get update && apt-get install -y --no-install-recommends \
    libpq-dev \
    gcc \
    && rm -rf /var/lib/apt/lists/*

# Copy workspace manifests
COPY pyproject.toml packages/ apps/api/pyproject.toml services/*/pyproject.toml ./

# Install all workspace packages (including dev to get build deps)
RUN uv sync --frozen --no-install-project --all-packages --extra dev

# ---- API build stage ----
FROM base AS api-build

COPY apps/api/src ./apps/api/src
COPY packages/contracts/src ./packages/contracts/src
COPY packages/shared/src ./packages/shared/src
COPY services/retrieval/src ./services/retrieval/src

RUN uv sync --frozen --all-packages --extra dev
# Re-install api package in editable mode to pick up src/ changes
RUN uv sync --frozen --extra dev

# ---- Runtime stage ----
FROM base AS runtime

ENV PYTHONUNBUFFERED=1
ENV PYTHONDONTWRITEBYTECODE=1

# Copy installed packages from build
COPY --from=api-build /app/.venv /app/.venv
COPY --from=api-build /app/apps/api/src /app/apps/api/src
COPY --from=api-build /app/packages/contracts/src /app/packages/contracts/src
COPY --from=api-build /app/packages/shared/src /app/packages/shared/src
COPY --from=api-build /app/services/retrieval/src /app/services/retrieval/src

# Ensure .venv python is on PATH
ENV PATH="/app/.venv/bin:$PATH"

# Run as non-root
RUN useradd --create-home --shell /bin/bash appuser
USER appuser

EXPOSE 8000

# Run alembic migrations then start API
ENTRYPOINT ["/bin/bash", "-c", "\
    echo 'Waiting for postgres...' && \
    python -c 'import socket,os; s=socket.socket(); s.connect((os.environ[\"POSTGRES_HOST\"],int(os.environ[\"POSTGRES_PORT\"]))); s.close()' && \
    echo 'Running migrations...' && \
    alembic -c apps/api/alembic.ini upgrade head && \
    echo 'Starting API...' && \
    uvicorn 'course_tutor_api:create_app()' --factory --host 0.0.0.0 --port 8000 \
"]
