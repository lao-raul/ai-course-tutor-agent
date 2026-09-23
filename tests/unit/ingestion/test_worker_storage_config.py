from __future__ import annotations

import pytest
from course_tutor_ingestion.cli import _configured_object_store

from course_tutor_shared import Settings


@pytest.mark.asyncio
async def test_disabled_source_artifacts_do_not_create_or_probe_minio() -> None:
    settings = Settings(store_source_artifacts=False, minio_endpoint="http://minio.invalid:9000")

    assert await _configured_object_store(settings) is None
