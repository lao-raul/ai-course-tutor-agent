"""Validated application configuration.

Every setting is sourced from the environment (or a local ``.env``) and validated at
startup, so a misconfigured deployment fails immediately rather than at first request.
"""

from __future__ import annotations

from enum import StrEnum
from functools import lru_cache
from pathlib import Path
from uuid import UUID

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


class AuthMode(StrEnum):
    LOCAL = "local"
    OIDC = "oidc"


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
    build_version: str = "0.1.0-dev"
    build_revision: str = "unknown"
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
    # Confirmed against the live host: qwen/qwen3.6-35b-a3b supports 262144 tokens.
    # Used to bound prompt budgets and enforce max context (design-spec §5).
    llm_chat_context_window: int = Field(default=262144, gt=0)

    # --- Course sources ---------------------------------------------------------
    # A local POSIX path only. SMB URLs are mounted by the host, never by the app.
    course_source_path: Path | None = None

    # --- Authentication ---------------------------------------------------------
    # Local mode is intentionally explicit and uses one fixed bearer token. It is
    # rejected in production, where signed OIDC JWTs are mandatory.
    auth_mode: AuthMode = AuthMode.LOCAL
    local_auth_token: SecretStr = SecretStr("local-dev-token")
    local_tenant_id: UUID = UUID("00000000-0000-0000-0000-000000000001")
    local_tenant_slug: str = "local"
    local_tenant_name: str = "Local Development"
    local_user_id: UUID = UUID("00000000-0000-0000-0000-000000000002")
    local_user_display_name: str = "Local Developer"
    local_user_role: str = "platform_admin"
    local_access_label: str = "restricted"
    oidc_issuer: str | None = None
    oidc_audience: str | None = None
    oidc_jwks_url: str | None = None
    oidc_algorithms: str = "RS256"

    # --- State stores -----------------------------------------------------------
    postgres_dsn: str = "postgresql+asyncpg://course_tutor:course_tutor@localhost:5432/course_tutor"
    qdrant_url: str = "http://localhost:6333"
    redis_url: str = "redis://localhost:6379/0"
    minio_endpoint: str = "http://localhost:9000"
    minio_access_key: str = "course-tutor"
    minio_secret_key: SecretStr = SecretStr("change-me-in-production")
    minio_bucket: str = "course-tutor-artifacts"

    # --- Background ingestion --------------------------------------------------
    ingestion_scan_interval_seconds: int = Field(default=900, ge=30)
    ingestion_poll_interval_seconds: int = Field(default=5, ge=1)
    ingestion_max_attempts: int = Field(default=5, ge=1, le=100)

    # --- Learner memory ---------------------------------------------------------
    # Long-term memory is opt-in in every environment. Session context is always
    # bounded independently from this preference.
    memory_extraction_interval: int = Field(default=2, ge=1, le=20)
    chat_turn_retention_days: int = Field(default=30, ge=1, le=365)
    session_summary_retention_days: int = Field(default=90, ge=1, le=730)

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

    @field_validator("local_user_role")
    @classmethod
    def _known_local_role(cls, value: str) -> str:
        allowed = {"student", "teaching_assistant", "instructor", "platform_admin"}
        if value not in allowed:
            raise ValueError(f"local_user_role must be one of {sorted(allowed)}")
        return value

    @field_validator("local_access_label")
    @classmethod
    def _known_local_access_label(cls, value: str) -> str:
        allowed = {"public", "enrolled", "staff_only", "restricted"}
        if value not in allowed:
            raise ValueError(f"local_access_label must be one of {sorted(allowed)}")
        return value

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
                    "(e.g. /Volumes/CourseContent/...), not a URL such as smb://"
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
            if self.auth_mode is not AuthMode.OIDC:
                raise ValueError("AUTH_MODE must be oidc in production")
            missing = [
                name
                for name, value in (
                    ("OIDC_ISSUER", self.oidc_issuer),
                    ("OIDC_AUDIENCE", self.oidc_audience),
                    ("OIDC_JWKS_URL", self.oidc_jwks_url),
                )
                if not value
            ]
            if missing:
                message = f"production OIDC configuration is incomplete: {', '.join(missing)}"
                raise ValueError(message)
            if not (self.oidc_issuer or "").startswith("https://") or not (
                self.oidc_jwks_url or ""
            ).startswith("https://"):
                raise ValueError("production OIDC issuer and JWKS URL must use HTTPS")
            algorithms = {item.strip() for item in self.oidc_algorithms.split(",") if item.strip()}
            allowed = {"RS256", "RS384", "RS512", "ES256", "ES384", "ES512"}
            if not algorithms or not algorithms.issubset(allowed):
                raise ValueError(
                    "production OIDC algorithms must be approved asymmetric algorithms"
                )
        return self

    @property
    def is_local(self) -> bool:
        return self.environment is Environment.LOCAL


@lru_cache(maxsize=1)
def get_settings() -> Settings:
    """Process-wide settings singleton. Call ``get_settings.cache_clear()`` in tests."""
    return Settings()
