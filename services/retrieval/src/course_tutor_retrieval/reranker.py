"""Reranking of retrieval candidates.

Phase 2 uses a simple score-based rerank.  A full cross-encoder LLM reranker
is planned for Phase 3.
"""

from __future__ import annotations

from course_tutor_contracts.retrieval import RetrievedChunk


class Reranker:
    """Reranks retrieval candidates.

    Current strategy: sort by descending score and enforce
    source diversity (no more than N chunks from the same file).
    """

    def __init__(self, max_from_same_source: int = 2) -> None:
        self._max_from_same_source = max_from_same_source

    def rerank(
        self,
        candidates: list[RetrievedChunk],
        *,
        max_from_same_source: int | None = None,
    ) -> list[RetrievedChunk]:
        """Reorder candidates for prompt diversity and relevance.

        Strategy:
        1. Sort by descending score.
        2. Window of top-N*2 candidates.
        3. Pick up to max_from_same_source per relative_path.
        4. Preserve relative order within same source.
        """
        if not candidates:
            return []

        # Sort by score descending
        sorted_cand = sorted(candidates, key=lambda c: c.score, reverse=True)

        source_limit = max_from_same_source or self._max_from_same_source
        chosen: list[RetrievedChunk] = []
        source_count: dict[str, int] = {}

        for chunk in sorted_cand:
            path = chunk.relative_path
            count = source_count.get(path, 0)
            if count < source_limit:
                chosen.append(chunk)
                source_count[path] = count + 1

        return chosen
