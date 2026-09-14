"""Dense retrieval with a small, accurately named lexical scoring heuristic."""

from __future__ import annotations

import asyncio
import time
import uuid

import structlog
from qdrant_client import QdrantClient
from qdrant_client.models import (
    FieldCondition,
    Filter,
    HasIdCondition,
    IsEmptyCondition,
    IsNullCondition,
    MatchAny,
    MatchValue,
    NestedCondition,
)

from course_tutor_api.providers.base import EmbeddingProvider
from course_tutor_contracts.enums import AccessLabel, AnchorType, ChunkClass
from course_tutor_contracts.retrieval import RetrievalResult, RetrievedChunk
from course_tutor_retrieval.collection import COLLECTION_NAME
from course_tutor_retrieval.scope import extract_content_scopes

logger = structlog.get_logger(__name__)

# Access label ordering: higher privilege includes lower
_ACCESS_LABEL_RANK = {
    AccessLabel.PUBLIC: 0,
    AccessLabel.ENROLLED: 1,
    AccessLabel.STAFF_ONLY: 2,
    AccessLabel.RESTRICTED: 3,
}

_FilterCondition = (
    FieldCondition | IsEmptyCondition | IsNullCondition | HasIdCondition | NestedCondition | Filter
)


class DenseRetrievalService:
    """Scope-filtered dense recall followed by a lexical score adjustment.

    Explicit Unit/Week references become a Qdrant payload filter before dense recall.
    This prevents similarly numbered but semantically different course sections from
    occupying the evidence set.
    """

    def __init__(
        self,
        qdrant_client: QdrantClient,
        embed_provider: EmbeddingProvider,
    ) -> None:
        self._client = qdrant_client
        self._embed = embed_provider

    async def search(
        self,
        query: str,
        tenant_id: uuid.UUID,
        course_id: uuid.UUID,
        content_version_id: uuid.UUID,
        access_label: AccessLabel,
        limit: int = 20,
    ) -> RetrievalResult:
        """Execute dense retrieval and return ranked candidates.

        Flow:
        1. Parse an optional typed Unit/Week scope
        2. Embed query → scope- and ACL-filtered Qdrant dense search
        3. Python-side keyword re-score
        """
        t0 = time.monotonic()

        query_vector = await self._embed.embed([query])
        t_embed = (time.monotonic() - t0) * 1000
        t_query = time.monotonic()
        query_scopes = extract_content_scopes(query)
        results = await asyncio.to_thread(
            self._client.query_points,
            collection_name=COLLECTION_NAME,
            query=query_vector[0],
            query_filter=self._build_filter(
                tenant_id,
                course_id,
                content_version_id,
                access_label,
                content_scopes=query_scopes,
            ),
            limit=limit * 3,
            with_payload=True,
        )
        t_dense = (time.monotonic() - t_query) * 1000

        candidates: list[RetrievedChunk] = []
        max_rank = _ACCESS_LABEL_RANK.get(access_label, 0)
        query_terms = set(query.lower().split())

        for point in results.points:
            payload = point.payload
            if payload is None:
                continue
            label_str = payload.get("access_label", "enrolled")
            try:
                label_enum = AccessLabel(label_str)
            except ValueError:
                label_enum = AccessLabel.ENROLLED

            if _ACCESS_LABEL_RANK.get(label_enum, 0) > max_rank:
                continue

            score = float(point.score)

            # Python-side keyword boost: if the text contains query terms, boost score
            text_lower = payload.get("text", "").lower()
            keyword_hits = sum(1 for term in query_terms if term in text_lower and len(term) >= 3)
            if keyword_hits > 0:
                score = score + (0.05 * keyword_hits)

            path_scopes = set(extract_content_scopes(payload.get("relative_path", "")))
            if set(query_scopes) & path_scopes:
                score += 0.35

            candidates.append(
                RetrievedChunk(
                    chunk_id=uuid.UUID(payload["chunk_id"]),
                    source_id=uuid.UUID(payload["source_id"]),
                    text=payload["text"],
                    relative_path=payload["relative_path"],
                    mime_type=payload.get("mime_type", "application/octet-stream"),
                    anchor_type=AnchorType(payload.get("anchor_type", "page")),
                    anchor_value=payload.get("anchor_value", "1"),
                    chunk_class=ChunkClass(payload.get("chunk_class", "content")),
                    score=round(score, 6),
                )
            )

        # Sort by score descending
        candidates.sort(key=lambda c: c.score, reverse=True)

        total = await asyncio.to_thread(
            self._count_indexed, tenant_id, course_id, content_version_id, access_label
        )

        return RetrievalResult(
            candidates=candidates[:limit],
            total_indexed=total,
            timings_ms={
                "embedding_ms": round(t_embed, 2),
                "dense_query_ms": round(t_dense, 2),
                "total_retrieval_ms": round((time.monotonic() - t0) * 1000, 2),
            },
        )

    def _build_filter(
        self,
        tenant_id: uuid.UUID,
        course_id: uuid.UUID,
        content_version_id: uuid.UUID,
        access_label: AccessLabel,
        content_scopes: tuple[str, ...] = (),
    ) -> Filter:
        allowed_labels = [
            label.value
            for label, rank in _ACCESS_LABEL_RANK.items()
            if rank <= _ACCESS_LABEL_RANK[access_label]
        ]
        conditions: list[_FilterCondition] = [
            FieldCondition(key="tenant_id", match=MatchValue(value=str(tenant_id))),
            FieldCondition(key="course_id", match=MatchValue(value=str(course_id))),
            FieldCondition(
                key="content_version_id", match=MatchValue(value=str(content_version_id))
            ),
            FieldCondition(key="access_label", match=MatchAny(any=allowed_labels)),
        ]
        if content_scopes:
            conditions.append(
                FieldCondition(
                    key="content_scopes",
                    match=MatchAny(any=list(content_scopes)),
                )
            )
        return Filter(must=conditions)

    def _count_indexed(
        self,
        tenant_id: uuid.UUID,
        course_id: uuid.UUID,
        content_version_id: uuid.UUID,
        access_label: AccessLabel,
    ) -> int:
        """Approximate count of indexed points for a content version."""
        try:
            result = self._client.count(
                collection_name=COLLECTION_NAME,
                count_filter=self._build_filter(
                    tenant_id, course_id, content_version_id, access_label
                ),
                exact=True,
            )
            return result.count or 0
        except Exception:
            return 0
