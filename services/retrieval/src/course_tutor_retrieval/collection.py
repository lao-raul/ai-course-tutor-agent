"""Qdrant collection lifecycle management."""

from __future__ import annotations

import structlog
from qdrant_client import QdrantClient
from qdrant_client.models import Distance, PayloadSchemaType, VectorParams

from course_tutor_shared import get_settings

logger = structlog.get_logger(__name__)

COLLECTION_NAME = "course_chunks"


def get_embedding_dimension() -> int:
    """Read the expected vector dimension from settings."""
    return get_settings().llm_embedding_dimension


async def ensure_collection(client: QdrantClient) -> None:
    """Create the course_chunks collection if it does not exist.

    Uses a single 1024-dimensional dense vector (matching the embedding model
    dimension from settings).  Sparse/TEXT_INDEX support requires Qdrant server
    >= 1.19; keyword fallback is handled at query time via Python-side filtering.
    """
    existing = [c.name for c in client.collections.get_collections().collections]
    if COLLECTION_NAME in existing:
        logger.debug("qdrant_collection_exists", collection=COLLECTION_NAME)
        return

    dim = get_embedding_dimension()
    client.create_collection(
        collection_name=COLLECTION_NAME,
        vectors_config={
            "": VectorParams(
                size=dim,
                distance=Distance.COSINE,
                on_disk=True,
            ),
        },
    )

    # Payload indexes for filtering.
    for field, schema in [
        ("tenant_id", PayloadSchemaType.KEYWORD),
        ("course_id", PayloadSchemaType.KEYWORD),
        ("content_version_id", PayloadSchemaType.KEYWORD),
        ("source_id", PayloadSchemaType.KEYWORD),
        ("chunk_id", PayloadSchemaType.KEYWORD),
        ("access_label", PayloadSchemaType.KEYWORD),
        ("chunk_class", PayloadSchemaType.KEYWORD),
        ("relative_path", PayloadSchemaType.KEYWORD),
        ("anchor_type", PayloadSchemaType.KEYWORD),
        ("mime_type", PayloadSchemaType.KEYWORD),
    ]:
        client.create_payload_index(
            collection_name=COLLECTION_NAME,
            field_name=field,
            field_schema=schema,
        )

    logger.info("qdrant_collection_created", collection=COLLECTION_NAME, dimension=dim)


async def recreate_collection(client: QdrantClient) -> None:
    """Delete and recreate the collection (for full re-index)."""
    existing = [c.name for c in client.collections.get_collections().collections]
    if COLLECTION_NAME in existing:
        client.delete_collection(collection_name=COLLECTION_NAME)
        logger.info("qdrant_collection_deleted", collection=COLLECTION_NAME)
    await ensure_collection(client)
