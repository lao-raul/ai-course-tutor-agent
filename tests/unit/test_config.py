"""Configuration validation.

These guard the two misconfigurations the specs single out as dangerous: an
``LLM_BASE_URL`` that already includes an endpoint, and a NAS URL used where a mounted
local path is required.
"""

from __future__ import annotations

import pytest
from pydantic import ValidationError

from course_tutor_shared import Settings
from course_tutor_shared.config import Environment, get_settings


def test_llm_base_url_rejects_endpoint_suffix() -> None:
    with pytest.raises(ValidationError, match="must be the API base"):
        Settings(llm_base_url="http://localhost:1234/v1/chat/completions")


def test_llm_base_url_strips_trailing_slash() -> None:
    assert Settings(llm_base_url="http://localhost:1234/v1/").llm_base_url == (
        "http://localhost:1234/v1"
    )


def test_course_source_path_rejects_smb_url() -> None:
    with pytest.raises(ValidationError, match="mounted local POSIX directory"):
        Settings(course_source_path="smb://example.invalid/share/modules")


def test_course_source_path_rejects_relative_path() -> None:
    with pytest.raises(ValidationError, match="absolute path"):
        Settings(course_source_path="data/modules")


def test_blank_course_source_path_is_unset() -> None:
    """An empty env var means "not configured yet", not the current directory."""
    assert Settings(course_source_path="").course_source_path is None


def test_unknown_log_level_rejected() -> None:
    with pytest.raises(ValidationError, match="log_level must be one of"):
        Settings(log_level="chatty")


def test_log_level_is_normalized() -> None:
    assert Settings(log_level="debug").log_level == "DEBUG"


def test_embedding_dimension_must_be_positive() -> None:
    with pytest.raises(ValidationError):
        Settings(llm_embedding_dimension=0)


def test_production_rejects_placeholder_secret() -> None:
    with pytest.raises(ValidationError, match="MINIO_SECRET_KEY"):
        Settings(
            environment=Environment.PRODUCTION,
            minio_secret_key="change-me-in-production",
        )


def test_secrets_are_not_reprarepr() -> None:
    """Secrets must not leak through logs or tracebacks that repr the settings."""
    settings = Settings(minio_secret_key="super-secret-value")
    assert "super-secret-value" not in repr(settings)
    assert settings.minio_secret_key.get_secret_value() == "super-secret-value"


def test_settings_are_frozen() -> None:
    settings = Settings()
    with pytest.raises(ValidationError):
        settings.log_level = "DEBUG"  # type: ignore[misc]


def test_get_settings_is_cached() -> None:
    assert get_settings() is get_settings()
