"""Vector indexing: embed chunks and upsert to Qdrant."""

from __future__ import annotations

import uuid
from typing import Any

import structlog
from qdrant_client import QdrantClient
from qdrant_client.models import FieldCondition, Filter, MatchValue, PointStruct

from course_tutor_retrieval.collection import COLLECTION_NAME, ensure_collection
from course_tutor_retrieval.scope import extract_content_scopes

logger = structlog.get_logger(__name__)

EMBEDDING_BATCH_SIZE = 32
UPSERT_BATCH_SIZE = 100


class EmbeddingIndexer:
    """Embeds text chunks and upserts dense vectors into Qdrant."""

    def __init__(
        self,
        qdrant_client: QdrantClient,
        embed_provider: Any,  # EmbeddingProvider but avoids circular import
    ) -> None:
        self._client = qdrant_client
        self._embed = embed_provider

    async def index_chunks(
        self,
        chunks: list[dict[str, object]],
        version: dict[str, object],
    ) -> int:
        """Index a list of chunk dicts for a content version.

        Each chunk dict must have: id, source_id, ordinal, text, anchor_type,
        anchor_value, chunk_class, relative_path, mime_type, access_label.
        Version dict must have: id, course_id, tenant_id.
        """
        if not chunks:
            return 0

        await ensure_collection(self._client)

        texts = [c["text"] for c in chunks]
        vectors: list[list[float]] = []
        for i in range(0, len(texts), EMBEDDING_BATCH_SIZE):
            text_batch = texts[i : i + EMBEDDING_BATCH_SIZE]
            vector_batch = await self._embed.embed(text_batch)
            if len(vector_batch) != len(text_batch):
                raise ValueError(
                    "embedding provider returned "
                    f"{len(vector_batch)} vectors for {len(text_batch)} texts"
                )
            vectors.extend(vector_batch)

        points = []
        for chunk, vector in zip(chunks, vectors, strict=True):
            anchor_type = chunk["anchor_type"]
            chunk_class = chunk["chunk_class"]
            access_label = chunk["access_label"]

            def _val(v: object) -> str:
                return v.value if hasattr(v, "value") else str(v)

            payload = {
                "tenant_id": str(version["tenant_id"]),
                "course_id": str(version["course_id"]),
                "content_version_id": str(version["id"]),
                "source_id": str(chunk["source_id"]),
                "chunk_id": str(chunk["id"]),
                "text": chunk["text"],
                "ordinal": chunk["ordinal"],
                "relative_path": chunk["relative_path"],
                "content_scopes": list(extract_content_scopes(str(chunk["relative_path"]))),
                "mime_type": chunk["mime_type"],
                "anchor_type": _val(anchor_type),
                "anchor_value": chunk["anchor_value"],
                "chunk_class": _val(chunk_class),
                "access_label": _val(access_label),
                "token_count": chunk.get("token_count", 0),
            }
            points.append(
                PointStruct(
                    id=str(chunk["id"]),
                    vector={"": vector},  # default dense vector
                    payload=payload,
                )
            )

        for i in range(0, len(points), UPSERT_BATCH_SIZE):
            batch = points[i : i + UPSERT_BATCH_SIZE]
            self._client.upsert(collection_name=COLLECTION_NAME, points=batch)
            logger.debug("qdrant_batch_upserted", count=len(batch))

        logger.info("qdrant_chunks_indexed", count=len(points))
        return len(points)

    async def delete_by_version(self, version_id: uuid.UUID) -> None:
        """Delete all vectors for a content version (used before re-index)."""
        self._client.delete(
            collection_name=COLLECTION_NAME,
            points_selector=Filter(
                must=[
                    FieldCondition(
                        key="content_version_id",
                        match=MatchValue(value=str(version_id)),
                    )
                ]
            ),
        )
        logger.info("qdrant_version_deleted", version_id=str(version_id))
