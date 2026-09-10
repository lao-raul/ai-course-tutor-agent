"""Retrieval service: dense recall, score/diversity ordering and evidence packaging."""

from course_tutor_retrieval.collection import (
    COLLECTION_NAME,
    ensure_collection,
    recreate_collection,
)
from course_tutor_retrieval.indexer import EmbeddingIndexer
from course_tutor_retrieval.reranker import Reranker
from course_tutor_retrieval.search import DenseRetrievalService

__all__ = [
    "COLLECTION_NAME",
    "DenseRetrievalService",
    "EmbeddingIndexer",
    "Reranker",
    "ensure_collection",
    "recreate_collection",
]
