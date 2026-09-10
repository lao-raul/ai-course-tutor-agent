"""Executable, synthetic RAG retrieval quality gate.

The benchmark invokes the production ``DenseRetrievalService`` with an in-memory,
deterministic vector backend. It requires neither course files, NAS, LM Studio nor
network services and writes machine-readable metrics for CI.
"""

from __future__ import annotations

import argparse
import asyncio
import json
import math
import re
import statistics
import time
import uuid
from dataclasses import dataclass
from pathlib import Path
from types import SimpleNamespace
from typing import Any

from course_tutor_retrieval.search import DenseRetrievalService

from course_tutor_api.routes.chat import MIN_RELEVANCE_SCORE
from course_tutor_contracts.enums import AccessLabel

SYNTHETIC_MODULES = [
    {
        "filename": "week1_introduction.txt",
        "content": (
            "Artificial Intelligence includes machine learning, natural language processing, "
            "computer vision and robotics. The Turing Test was proposed by Alan Turing in 1950 "
            "and asks whether a human can distinguish a machine response."
        ),
    },
    {
        "filename": "week2_search.txt",
        "content": (
            "Breadth-First Search BFS explores each depth and has O(b^d) time where b is "
            "branching factor. Depth-First Search DFS explores branches using O(d) space. A* "
            "Search uses f(n)=g(n)+h(n). An admissible heuristic never overestimates. The "
            "8-puzzle optimal solution commonly needs 20-30 moves."
        ),
    },
    {
        "filename": "week3_logic.txt",
        "content": (
            "Propositional Logic includes modus ponens: from P and P IMPLIES Q infer Q. "
            "First-Order Logic adds forall and exists quantifiers. STRIPS planning represents "
            "actions with preconditions and effects in domains such as Blocks World."
        ),
    },
    {
        "filename": "week4_probability.txt",
        "content": (
            "Bayes Rule is P(A|B)=P(B|A) times P(A) divided by P(B). Bayesian Networks are "
            "directed acyclic graphs. A Hidden Markov Model HMM contains hidden states, "
            "observations, a transition model and an observation model. Viterbi finds the most "
            "likely hidden-state sequence."
        ),
    },
    {
        "filename": "exercises_week3.txt",
        "content": (
            "Exercise: express every student who passes is happy as forall x: Student(x) AND "
            "Pass(x) IMPLIES Happy(x). Logic solution hints use modus ponens."
        ),
    },
]

BENCHMARK_CASES = [
    ("q1", "What is the Turing Test and who proposed it?", {"week1_introduction.txt"}, False),
    (
        "q2",
        "What is the time complexity of BFS and what does b represent?",
        {"week2_search.txt"},
        False,
    ),
    ("q3", "What are the BFS DFS and A* search algorithms?", {"week2_search.txt"}, False),
    ("q4", "What is Bayes Rule?", {"week4_probability.txt"}, False),
    ("q5", "How does modus ponens infer Q?", {"week3_logic.txt"}, False),
    ("q6", "Express every student who passes is happy in FOL", {"exercises_week3.txt"}, False),
    ("q7", "What is the optimal solution length for the 8-puzzle?", {"week2_search.txt"}, False),
    ("q8", "What is the Viterbi algorithm used for?", {"week4_probability.txt"}, False),
    ("q9", "What is covered about convolutional neural networks?", set(), True),
    ("q10", "What are the components of a Hidden Markov Model?", {"week4_probability.txt"}, False),
]

_TOKEN = re.compile(r"[a-z0-9*]+", re.IGNORECASE)
_STOPWORDS = {
    "a",
    "about",
    "and",
    "are",
    "does",
    "for",
    "how",
    "in",
    "is",
    "it",
    "of",
    "the",
    "to",
    "what",
    "who",
}


def _tokens(value: str) -> list[str]:
    return [token.lower() for token in _TOKEN.findall(value) if token.lower() not in _STOPWORDS]


class _Vectorizer:
    def __init__(self, texts: list[str]) -> None:
        documents = [set(_tokens(text)) for text in texts]
        self.vocabulary = sorted(set().union(*documents))
        count = len(documents)
        self.idf = {
            term: math.log((count + 1) / (1 + sum(term in doc for doc in documents))) + 1
            for term in self.vocabulary
        }

    def vector(self, text: str) -> list[float]:
        terms = _tokens(text)
        values = [terms.count(term) * self.idf[term] for term in self.vocabulary]
        norm = math.sqrt(sum(value * value for value in values)) or 1.0
        return [value / norm for value in values]


class _Embedder:
    def __init__(self, vectorizer: _Vectorizer) -> None:
        self.vectorizer = vectorizer

    async def embed(self, texts: list[str]) -> list[list[float]]:
        return [self.vectorizer.vector(text) for text in texts]


@dataclass(frozen=True, slots=True)
class _Document:
    path: str
    text: str
    vector: list[float]


class _VectorBackend:
    def __init__(self, documents: list[_Document]) -> None:
        self.documents = documents

    def query_points(self, *, query: list[float], limit: int, **_kwargs: Any) -> object:
        points = []
        for document in self.documents:
            score = sum(left * right for left, right in zip(query, document.vector, strict=True))
            points.append(
                SimpleNamespace(
                    score=score,
                    payload={
                        "chunk_id": str(uuid.uuid5(uuid.NAMESPACE_URL, f"chunk:{document.path}")),
                        "source_id": str(uuid.uuid5(uuid.NAMESPACE_URL, f"source:{document.path}")),
                        "text": document.text,
                        "relative_path": document.path,
                        "mime_type": "text/plain",
                        "anchor_type": "page",
                        "anchor_value": "1",
                        "chunk_class": "content",
                        "access_label": "enrolled",
                    },
                )
            )
        points.sort(key=lambda point: point.score, reverse=True)
        return SimpleNamespace(points=points[:limit])

    def count(self, **_kwargs: Any) -> object:
        return SimpleNamespace(count=len(self.documents))


def _percentile(values: list[float], quantile: float) -> float:
    ordered = sorted(values)
    index = min(len(ordered) - 1, math.ceil(len(ordered) * quantile) - 1)
    return ordered[index]


async def run_benchmark() -> dict[str, Any]:
    corpus = [module["content"] for module in SYNTHETIC_MODULES]
    vectorizer = _Vectorizer(corpus)
    documents = [
        _Document(module["filename"], module["content"], vectorizer.vector(module["content"]))
        for module in SYNTHETIC_MODULES
    ]
    service = DenseRetrievalService(  # type: ignore[arg-type]
        _VectorBackend(documents), _Embedder(vectorizer)
    )
    tenant_id, course_id, version_id = uuid.uuid4(), uuid.uuid4(), uuid.uuid4()

    case_results: list[dict[str, Any]] = []
    reciprocal_ranks: list[float] = []
    recall_hits = 0
    citation_true = 0
    citation_total = 0
    abstain_true_positive = 0
    abstain_false_positive = 0
    abstain_false_negative = 0
    latencies: list[float] = []

    for case_id, question, expected_sources, should_abstain in BENCHMARK_CASES:
        started = time.perf_counter()
        result = await service.search(
            question,
            tenant_id,
            course_id,
            version_id,
            AccessLabel.ENROLLED,
            limit=5,
        )
        latency_ms = (time.perf_counter() - started) * 1000
        latencies.append(latency_ms)
        ranked_sources = [candidate.relative_path for candidate in result.candidates]
        top_score = result.candidates[0].score if result.candidates else 0.0
        predicted_abstain = top_score < MIN_RELEVANCE_SCORE

        rank = next(
            (index for index, source in enumerate(ranked_sources, 1) if source in expected_sources),
            None,
        )
        if not should_abstain:
            recall_hits += int(rank is not None and rank <= 5)
            reciprocal_ranks.append(1 / rank if rank else 0.0)
            if not predicted_abstain and ranked_sources:
                citation_total += 1
                citation_true += int(ranked_sources[0] in expected_sources)
        if predicted_abstain and should_abstain:
            abstain_true_positive += 1
        elif predicted_abstain:
            abstain_false_positive += 1
        elif should_abstain:
            abstain_false_negative += 1

        case_results.append(
            {
                "id": case_id,
                "top_sources": ranked_sources,
                "top_score": top_score,
                "expected_sources": sorted(expected_sources),
                "predicted_abstain": predicted_abstain,
                "should_abstain": should_abstain,
                "latency_ms": round(latency_ms, 3),
            }
        )

    answerable = sum(not case[3] for case in BENCHMARK_CASES)
    abstain_precision = abstain_true_positive / max(
        1, abstain_true_positive + abstain_false_positive
    )
    abstain_recall = abstain_true_positive / max(1, abstain_true_positive + abstain_false_negative)
    abstain_f1 = (
        2 * abstain_precision * abstain_recall / (abstain_precision + abstain_recall)
        if abstain_precision + abstain_recall
        else 0.0
    )
    return {
        "summary": {
            "recall_at_5": recall_hits / answerable,
            "mrr": statistics.fmean(reciprocal_ranks),
            "citation_precision": citation_true / max(1, citation_total),
            "abstention_precision": abstain_precision,
            "abstention_recall": abstain_recall,
            "abstention_f1": abstain_f1,
            "latency_p50_ms": statistics.median(latencies),
            "latency_p95_ms": _percentile(latencies, 0.95),
        },
        "cases": case_results,
    }


def main() -> int:
    parser = argparse.ArgumentParser()
    parser.add_argument("--output", type=Path, required=True)
    parser.add_argument("--recall-threshold", type=float, default=0.85)
    parser.add_argument("--mrr-threshold", type=float, default=0.80)
    parser.add_argument("--citation-threshold", type=float, default=0.95)
    parser.add_argument("--abstention-f1-threshold", type=float, default=0.90)
    parser.add_argument("--p95-latency-threshold-ms", type=float, default=250.0)
    args = parser.parse_args()

    metrics = asyncio.run(run_benchmark())
    args.output.parent.mkdir(parents=True, exist_ok=True)
    args.output.write_text(json.dumps(metrics, indent=2, sort_keys=True), encoding="utf-8")
    summary = metrics["summary"]
    print(json.dumps(summary, indent=2, sort_keys=True))
    failed = (
        summary["recall_at_5"] < args.recall_threshold
        or summary["mrr"] < args.mrr_threshold
        or summary["citation_precision"] < args.citation_threshold
        or summary["abstention_f1"] < args.abstention_f1_threshold
        or summary["latency_p95_ms"] > args.p95_latency_threshold_ms
    )
    return 1 if failed else 0


if __name__ == "__main__":
    raise SystemExit(main())
