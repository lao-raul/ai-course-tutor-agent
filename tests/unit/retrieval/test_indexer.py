from __future__ import annotations

import uuid

import pytest
from course_tutor_retrieval import indexer as indexer_module
from course_tutor_retrieval.indexer import EmbeddingIndexer


class _RecordingEmbedder:
    def __init__(self, *, omit_last_vector: bool = False) -> None:
        self.batch_sizes: list[int] = []
        self.omit_last_vector = omit_last_vector

    async def embed(self, texts: list[str]) -> list[list[float]]:
        self.batch_sizes.append(len(texts))
        vectors = [[float(len(text))] for text in texts]
        if self.omit_last_vector and vectors:
            return vectors[:-1]
        return vectors


class _RecordingQdrant:
    def __init__(self) -> None:
        self.upsert_sizes: list[int] = []
        self.points: list[object] = []
        self.delete_selectors: list[object] = []

    def upsert(self, *, collection_name: str, points: list[object]) -> None:
        assert collection_name
        self.upsert_sizes.append(len(points))
        self.points.extend(points)

    def delete(self, *, collection_name: str, points_selector: object) -> None:
        assert collection_name
        self.delete_selectors.append(points_selector)


def _chunks(count: int) -> list[dict[str, object]]:
    return [
        {
            "id": uuid.uuid4(),
            "source_id": uuid.uuid4(),
            "ordinal": ordinal,
            "text": f"course chunk {ordinal}",
            "anchor_type": "page",
            "anchor_value": str(ordinal + 1),
            "chunk_class": "content",
            "relative_path": "unit1/slides.pdf",
            "mime_type": "application/pdf",
            "access_label": "enrolled",
            "token_count": 3,
        }
        for ordinal in range(count)
    ]


@pytest.mark.asyncio
async def test_indexer_batches_embedding_requests(monkeypatch: pytest.MonkeyPatch) -> None:
    async def _collection_ready(_client: object) -> None:
        return None

    monkeypatch.setattr(indexer_module, "ensure_collection", _collection_ready)
    embedder = _RecordingEmbedder()
    qdrant = _RecordingQdrant()
    indexer = EmbeddingIndexer(qdrant, embedder)  # type: ignore[arg-type]

    indexed = await indexer.index_chunks(
        _chunks(65),
        {"id": uuid.uuid4(), "course_id": uuid.uuid4(), "tenant_id": uuid.uuid4()},
    )

    assert indexed == 65
    assert embedder.batch_sizes == [32, 32, 1]
    assert qdrant.upsert_sizes == [65]
    first_payload = qdrant.points[0].payload  # type: ignore[attr-defined]
    assert first_payload["content_scopes"] == ["unit:1"]


@pytest.mark.asyncio
async def test_indexer_rejects_partial_embedding_response(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    async def _collection_ready(_client: object) -> None:
        return None

    monkeypatch.setattr(indexer_module, "ensure_collection", _collection_ready)
    indexer = EmbeddingIndexer(  # type: ignore[arg-type]
        _RecordingQdrant(),
        _RecordingEmbedder(omit_last_vector=True),
    )

    with pytest.raises(ValueError, match="31 vectors for 32 texts"):
        await indexer.index_chunks(
            _chunks(32),
            {"id": uuid.uuid4(), "course_id": uuid.uuid4(), "tenant_id": uuid.uuid4()},
        )


@pytest.mark.asyncio
async def test_indexer_deletes_only_explicit_orphan_sources() -> None:
    qdrant = _RecordingQdrant()
    indexer = EmbeddingIndexer(qdrant, _RecordingEmbedder())  # type: ignore[arg-type]
    source_ids = [uuid.uuid4(), uuid.uuid4()]

    await indexer.delete_sources([])
    await indexer.delete_sources(source_ids)

    assert len(qdrant.delete_selectors) == 1
    selector = qdrant.delete_selectors[0]
    condition = selector.must[0]  # type: ignore[union-attr]
    assert condition.key == "source_id"
    assert condition.match.any == [str(item) for item in source_ids]
