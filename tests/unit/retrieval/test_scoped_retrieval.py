from __future__ import annotations

import uuid
from types import SimpleNamespace

import pytest
from course_tutor_retrieval.scope import extract_content_scopes
from course_tutor_retrieval.search import DenseRetrievalService

from course_tutor_contracts.enums import AccessLabel


class _Embedder:
    async def embed(self, texts: list[str]) -> list[list[float]]:
        assert texts
        return [[0.0] for _ in texts]


class _Qdrant:
    def __init__(self) -> None:
        self.filter = None

    def query_points(self, **kwargs: object) -> object:
        self.filter = kwargs["query_filter"]
        return SimpleNamespace(
            points=[
                self._point("Quiz/Week2_Formative_Quiz.docx", 0.90),
                self._point("webinar/unit2/Unit2_slides.pdf", 0.70),
            ]
        )

    @staticmethod
    def _point(path: str, score: float) -> object:
        return SimpleNamespace(
            score=score,
            payload={
                "chunk_id": str(uuid.uuid4()),
                "source_id": str(uuid.uuid4()),
                "text": path,
                "relative_path": path,
                "access_label": "enrolled",
            },
        )

    def count(self, **_kwargs: object) -> object:
        return SimpleNamespace(count=2)


def test_scope_extraction_preserves_unit_week_kind() -> None:
    assert extract_content_scopes("summarize Unit 02") == ("unit:2",)
    assert extract_content_scopes("Quiz/Week2_Formative_Quiz.docx") == ("week:2",)
    assert extract_content_scopes("webinar/unit2/Unit2_slides.pdf") == ("unit:2",)
    assert extract_content_scopes("compare Unit 2 with Week 2") == ("unit:2", "week:2")


@pytest.mark.asyncio
async def test_unit_query_filters_and_boosts_only_the_matching_unit() -> None:
    client = _Qdrant()
    service = DenseRetrievalService(client, _Embedder())  # type: ignore[arg-type]

    result = await service.search(
        "give a summarize of unit 2",
        tenant_id=uuid.uuid4(),
        course_id=uuid.uuid4(),
        content_version_id=uuid.uuid4(),
        access_label=AccessLabel.ENROLLED,
    )

    dumped_filter = client.filter.model_dump(mode="json")
    assert "content_scopes" in str(dumped_filter)
    assert "unit:2" in str(dumped_filter)
    assert "week:2" not in str(dumped_filter)
    assert result.candidates[0].relative_path == "webinar/unit2/Unit2_slides.pdf"
    assert result.candidates[0].score == pytest.approx(1.10)
    assert result.candidates[1].score == pytest.approx(0.90)
