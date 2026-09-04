"""Hybrid retrieval: dense vector search with keyword boost."""

from __future__ import annotations

import uuid

import structlog
from qdrant_client import QdrantClient
from qdrant_client.models import FieldCondition, Filter, MatchValue

from course_tutor_api.providers.base import EmbeddingProvider
from course_tutor_contracts.enums import AccessLabel, AnchorType, ChunkClass
from course_tutor_contracts.retrieval import RetrievalResult, RetrievedChunk
from course_tutor_retrieval.collection import COLLECTION_NAME

logger = structlog.get_logger(__name__)

# Reciprocal Rank Fusion k parameter
RRF_K = 60

# Access label ordering: higher privilege includes lower
_ACCESS_LABEL_RANK = {
    AccessLabel.PUBLIC: 0,
    AccessLabel.ENROLLED: 1,
    AccessLabel.STAFF_ONLY: 2,
    AccessLabel.RESTRICTED: 3,
}

# Minimum score below which we abstain
SCORE_THRESHOLD = 0.3


class HybridRetrievalService:
    """Dense vector search with Python-side keyword matching boost."""

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
        course_id: uuid.UUID,
        content_version_id: uuid.UUID,
        access_label: AccessLabel,
        limit: int = 20,
    ) -> RetrievalResult:
        """Execute dense retrieval and return ranked candidates.

        Flow:
        1. Embed query → Qdrant dense search
        2. Python-side keyword re-score (boost docs with query terms)
        3. Filter by access_label
        """
        import time

        t0 = time.monotonic()

        query_vector = await self._embed.embed([query])
        results = self._client.query_points(
            collection_name=COLLECTION_NAME,
            query=query_vector[0],
            query_filter=self._build_filter(course_id, content_version_id),
            limit=limit * 3,  # over-fetch for post-filter headroom
            with_payload=True,
        )
        t_dense = (time.monotonic() - t0) * 1000

        candidates: list[RetrievedChunk] = []
        min_rank = _ACCESS_LABEL_RANK.get(access_label, 0)
        query_terms = set(query.lower().split())

        for point in results.points:
            payload = point.payload
            label_str = payload.get("access_label", "enrolled")
            try:
                label_enum = AccessLabel(label_str)
            except ValueError:
                label_enum = AccessLabel.ENROLLED

            if _ACCESS_LABEL_RANK.get(label_enum, 0) < min_rank:
                continue

            score = float(point.score)

            # Python-side keyword boost: if the text contains query terms, boost score
            text_lower = payload.get("text", "").lower()
            keyword_hits = sum(1 for term in query_terms if term in text_lower and len(term) >= 3)
            if keyword_hits > 0:
                score = score + (0.05 * keyword_hits)

            # Explicit unit/section path boost: when the query references a specific
            # unit or section by name (e.g. "unit 3", "unit3", "week 2"), boost chunks
            # whose relative_path points to that unit.  This reliably surfaces the right
            # unit even when the embedding model is biased toward overview content or
            # when query language (e.g. Chinese + English unit names) creates a semantic
            # gap between query and specific-unit content.
            import re

            def unit_boost(query_text: str, path: str) -> float:
                """Return a boost value if query references the same unit as the path."""
                query_lower = query_text.lower()
                # Extract unit/week references: "unit 3", "unit3", "week2", etc.
                unit_refs = re.findall(r"(?:unit|week)[_\s]*(\d+)", query_lower)
                if not unit_refs:
                    return 0.0
                path_lower = path.lower()
                for ref in unit_refs:
                    # Match "unitN" or "unit/N" style path segments
                    if re.search(rf"(?:^|/)unit[_\s]*{re.escape(ref)}(?:[/_\s]|$)", path_lower) or \
                       re.search(rf"(?:^|/)week[_\s]*{re.escape(ref)}(?:[/_\s]|$)", path_lower):
                        return 0.35  # strong enough to overcome embedding bias for overview content
                return 0.0

            score += unit_boost(query, payload.get("relative_path", ""))

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

        total = self._count_indexed(course_id, content_version_id)

        return RetrievalResult(
            candidates=candidates[:limit],
            total_indexed=total,
            timings_ms={"dense_ms": round(t_dense, 2)},
        )

    def _build_filter(
        self,
        course_id: uuid.UUID,
        content_version_id: uuid.UUID,
    ) -> Filter:
        return Filter(
            must=[
                FieldCondition(key="course_id", match=MatchValue(value=str(course_id))),
                FieldCondition(
                    key="content_version_id", match=MatchValue(value=str(content_version_id))
                ),
            ]
        )

    def _count_indexed(self, course_id: uuid.UUID, content_version_id: uuid.UUID) -> int:
        """Approximate count of indexed points for a content version."""
        try:
            result = self._client.count(
                collection_name=COLLECTION_NAME,
                count_filter=self._build_filter(course_id, content_version_id),
                exact=True,
            )
            return result.count or 0
        except Exception:
            return 0
