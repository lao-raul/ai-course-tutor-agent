# syntax=docker/dockerfile:1.7
ARG PYTHON_IMAGE=python:3.12.11-slim-bookworm

FROM ${PYTHON_IMAGE} AS build
ARG UV_VERSION=0.12.6
WORKDIR /app
RUN pip install --no-cache-dir "uv==${UV_VERSION}"
COPY . .
RUN uv sync --frozen --no-dev --package course-tutor-practice

FROM ${PYTHON_IMAGE} AS runtime
ARG BUILD_VERSION=0.1.0-dev
ARG BUILD_REVISION=unknown
ARG BUILD_SOURCE=https://github.com/example/ai-course-tutor-agent
LABEL org.opencontainers.image.title="course-tutor-practice-api" \
      org.opencontainers.image.version="${BUILD_VERSION}" \
      org.opencontainers.image.revision="${BUILD_REVISION}" \
      org.opencontainers.image.source="${BUILD_SOURCE}"
ENV PATH="/app/.venv/bin:$PATH" \
    PYTHONUNBUFFERED=1 \
    PYTHONDONTWRITEBYTECODE=1 \
    SERVICE_NAME=practice-api \
    BUILD_VERSION="${BUILD_VERSION}" \
    BUILD_REVISION="${BUILD_REVISION}"
WORKDIR /app
RUN apt-get update \
    && apt-get upgrade --yes --no-install-recommends \
    && rm -rf /var/lib/apt/lists/* \
    && useradd --create-home --uid 10001 appuser
COPY --from=build /app/.venv /app/.venv
COPY --from=build /app/apps/practice /app/apps/practice
COPY --from=build /app/packages/auth /app/packages/auth
COPY --from=build /app/packages/contracts /app/packages/contracts
COPY --from=build /app/packages/shared /app/packages/shared
USER 10001:10001
EXPOSE 8001
HEALTHCHECK --interval=30s --timeout=5s --start-period=5s --retries=3 \
  CMD python -c "import urllib.request; urllib.request.urlopen('http://127.0.0.1:8001/healthz', timeout=3)"
ENTRYPOINT ["uvicorn", "course_tutor_practice.app:create_app", "--factory", "--host", "0.0.0.0", "--port", "8001"]
