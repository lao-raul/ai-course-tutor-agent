FROM python:3.12.11-slim-bookworm
ARG BUILD_VERSION=0.1.0-dev
ARG BUILD_REVISION=unknown
LABEL org.opencontainers.image.title="course-tutor-fake-llm" \
      org.opencontainers.image.version="${BUILD_VERSION}" \
      org.opencontainers.image.revision="${BUILD_REVISION}"
RUN apt-get update \
    && apt-get upgrade --yes --no-install-recommends \
    && rm -rf /var/lib/apt/lists/*
WORKDIR /app
COPY infra/fake-llm/server.py /app/server.py
USER 65534:65534
EXPOSE 8082
HEALTHCHECK --interval=10s --timeout=3s --retries=3 \
  CMD python -c "import urllib.request; urllib.request.urlopen('http://127.0.0.1:8082/v1/models', timeout=2)"
ENTRYPOINT ["python", "/app/server.py"]
