from __future__ import annotations

from tests.retrieval_benchmark import run_benchmark


async def test_synthetic_benchmark_meets_quality_floor() -> None:
    metrics = await run_benchmark()
    summary = metrics["summary"]
    assert summary["recall_at_5"] >= 0.85
    assert summary["citation_precision"] >= 0.95
    assert summary["abstention_f1"] >= 0.90
