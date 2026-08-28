"""Validated application configuration.

Every setting is sourced from the environment (or a local ``.env``) and validated at
startup, so a misconfigured deployment fails immediately rather than at first request.
"""

from __future__ import annotations

from enum import StrEnum
from functools import lru_cache
from pathlib import Path

from pydantic import Field, SecretStr, field_validator, model_validator
from pydantic_settings import BaseSettings, SettingsConfigDict

_REPO_ROOT = Path(__file__).resolve().parents[4]


class Environment(StrEnum):
    LOCAL = "local"
    TEST = "test"
    PRODUCTION = "production"


class LogFormat(StrEnum):
    CONSOLE = "console"
    JSON = "json"


class Settings(BaseSettings):
    """Runtime configuration for all Python services."""

    model_config = SettingsConfigDict(
        env_file=_REPO_ROOT / ".env",
        env_file_encoding="utf-8",
        extra="ignore",
        frozen=True,
    )

    environment: Environment = Environment.LOCAL
    service_name: str = "course-tutor"
    log_level: str = "INFO"
    log_format: LogFormat = LogFormat.CONSOLE

    # --- Inference (LM Studio, OpenAI-compatible) -------------------------------
    llm_base_url: str = "http://localhost:1234/v1"
    llm_api_key: SecretStr = SecretStr("lm-studio")
    llm_chat_model: str = "local-model"
    llm_embedding_model: str = "local-embedding-model"
    # Fixes the Qdrant collection shape. A provider reporting a different width must
    # fail closed rather than silently index unusable vectors (function-spec §7.4).
    llm_embedding_dimension: int = Field(default=1024, gt=0)

    # --- Course sources ---------------------------------------------------------
    # A local POSIX path only. SMB URLs are mounted by the host, never by the app.
    course_source_path: Path | None = None

    # --- State stores -----------------------------------------------------------
    postgres_dsn: str = "postgresql+asyncpg://course_tutor:course_tutor@localhost:5432/course_tutor"
    qdrant_url: str = "http://localhost:6333"
    redis_url: str = "redis://localhost:6379/0"
    minio_endpoint: str = "http://localhost:9000"
    minio_access_key: str = "course-tutor"
    minio_secret_key: SecretStr = SecretStr("change-me-in-production")

    # --- Tracing ----------------------------------------------------------------
    otel_enabled: bool = False
    otel_exporter_otlp_endpoint: str | None = None

    @field_validator("llm_base_url")
    @classmethod
    def _reject_endpoint_suffix(cls, value: str) -> str:
        """``LLM_BASE_URL`` is a base, not a full endpoint."""
        normalized = value.rstrip("/")
        for suffix in ("/chat/completions", "/embeddings", "/completions"):
            if normalized.endswith(suffix):
                raise ValueError(
                    f"LLM_BASE_URL must be the API base (e.g. http://host:1234/v1), "
                    f"not the {suffix} endpoint"
                )
        return normalized

    @field_validator("log_level")
    @classmethod
    def _known_log_level(cls, value: str) -> str:
        allowed = {"DEBUG", "INFO", "WARNING", "ERROR", "CRITICAL"}
        upper = value.upper()
        if upper not in allowed:
            raise ValueError(f"log_level must be one of {sorted(allowed)}")
        return upper

    @field_validator("course_source_path", mode="before")
    @classmethod
    def _reject_url_source_root(cls, value: object) -> object:
        """Runs before ``Path`` coercion.

        ``Path("smb://host")`` silently collapses the double slash to ``smb:/host``, so a
        URL check after coercion would never fire. The host mounts the NAS; the
        application only ever reads a local path (function-spec §7.5).
        """
        if isinstance(value, str):
            if not value.strip():
                # An empty env var means "not configured", not the current directory.
                return None
            if "://" in value:
                raise ValueError(
                    "COURSE_SOURCE_PATH must be a mounted local POSIX directory "
                    "(e.g. /Volumes/L-NAS/...), not a URL such as smb://"
                )
        return value

    @field_validator("course_source_path")
    @classmethod
    def _require_absolute_path(cls, value: Path | None) -> Path | None:
        if value is None:
            return None
        if not value.is_absolute():
            raise ValueError("COURSE_SOURCE_PATH must be an absolute path")
        return value

    @model_validator(mode="after")
    def _production_requires_real_secrets(self) -> Settings:
        if self.environment is Environment.PRODUCTION:
            if self.minio_secret_key.get_secret_value() == "change-me-in-production":
                raise ValueError("MINIO_SECRET_KEY must be changed outside local development")
        return self

    @property
    def is_local(self) -> bool:
        return self.environment is Environment.LOCAL


@lru_cache(maxsize=1)
def get_settings() -> Settings:
    """Process-wide settings singleton. Call ``get_settings.cache_clear()`` in tests."""
    return Settings()
