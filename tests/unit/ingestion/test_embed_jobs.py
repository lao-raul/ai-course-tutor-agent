from __future__ import annotations

import uuid
from types import SimpleNamespace

import pytest
from course_tutor_ingestion.embed_jobs import CHUNK_PAGE_SIZE, _process_embed_event

from course_tutor_contracts.enums import ContentVersionStatus


class _Result:
    def __init__(self, rows: list[SimpleNamespace]) -> None:
        self._rows = rows

    def all(self) -> list[SimpleNamespace]:
        return self._rows


class _Session:
    def __init__(self, version: SimpleNamespace, course: SimpleNamespace) -> None:
        self._gets = [version, course]
        self._pages = [self._rows(CHUNK_PAGE_SIZE), self._rows(1), []]
        self.update_count = 0
        self.flush_count = 0

    @staticmethod
    def _rows(count: int) -> list[SimpleNamespace]:
        return [
            SimpleNamespace(
                chunk_id=uuid.uuid4(),
                source_id=uuid.uuid4(),
                ordinal=ordinal,
                text=f"chunk {ordinal}",
                anchor_type="page",
                anchor_value=str(ordinal + 1),
                chunk_class="content",
                token_count=2,
                relative_path="unit1/slides.pdf",
                mime_type="application/pdf",
                access_label="enrolled",
            )
            for ordinal in range(count)
        ]

    async def get(self, *_args: object, **_kwargs: object) -> SimpleNamespace:
        return self._gets.pop(0)

    async def execute(self, statement: object) -> _Result:
        if getattr(statement, "is_select", False):
            return _Result(self._pages.pop(0))
        self.update_count += 1
        return _Result([])

    async def flush(self) -> None:
        self.flush_count += 1


class _Indexer:
    def __init__(self) -> None:
        self.page_sizes: list[int] = []

    async def index_chunks(
        self, chunks: list[dict[str, object]], _version: dict[str, object]
    ) -> int:
        self.page_sizes.append(len(chunks))
        return len(chunks)


@pytest.mark.asyncio
async def test_embedding_job_pages_chunks_without_loading_entire_version() -> None:
    course_id = uuid.uuid4()
    version = SimpleNamespace(
        id=uuid.uuid4(),
        course_id=course_id,
        status=ContentVersionStatus.BUILDING,
        embedding_model_version=None,
    )
    course = SimpleNamespace(id=course_id, tenant_id=uuid.uuid4())
    event = SimpleNamespace(payload={"version_id": str(version.id), "course_id": str(course_id)})
    session = _Session(version, course)
    indexer = _Indexer()

    stats = await _process_embed_event(  # type: ignore[arg-type]
        session,
        event,
        indexer,
        "qwen-embedding",
    )

    assert stats.chunks_indexed == CHUNK_PAGE_SIZE + 1
    assert indexer.page_sizes == [CHUNK_PAGE_SIZE, 1]
    assert session.update_count == 2
    assert session.flush_count == 2
    assert version.status == ContentVersionStatus.READY
    assert version.embedding_model_version == "qwen-embedding"
