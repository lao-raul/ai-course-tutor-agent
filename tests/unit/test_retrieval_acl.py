from __future__ import annotations

import uuid
from types import SimpleNamespace

import pytest
from course_tutor_retrieval.search import DenseRetrievalService

from course_tutor_contracts.enums import AccessLabel


class _Embedder:
    async def embed(self, texts: list[str]) -> list[list[float]]:
        return [[0.0] for _ in texts]


class _Qdrant:
    def __init__(self) -> None:
        self.filter = None

    def query_points(self, **kwargs: object) -> object:
        self.filter = kwargs["query_filter"]
        labels = ["public", "enrolled", "staff_only", "restricted"]
        return SimpleNamespace(
            points=[
                SimpleNamespace(
                    score=0.8,
                    payload={
                        "chunk_id": str(uuid.uuid4()),
                        "source_id": str(uuid.uuid4()),
                        "text": label,
                        "relative_path": f"{label}.md",
                        "access_label": label,
                    },
                )
                for label in labels
            ]
        )

    def count(self, **_kwargs: object) -> object:
        return SimpleNamespace(count=4)


@pytest.mark.asyncio
@pytest.mark.parametrize(
    ("rank", "visible"),
    [
        (AccessLabel.PUBLIC, {"public"}),
        (AccessLabel.ENROLLED, {"public", "enrolled"}),
        (AccessLabel.STAFF_ONLY, {"public", "enrolled", "staff_only"}),
        (AccessLabel.RESTRICTED, {"public", "enrolled", "staff_only", "restricted"}),
    ],
)
async def test_acl_matrix_is_fail_closed(rank: AccessLabel, visible: set[str]) -> None:
    client = _Qdrant()
    service = DenseRetrievalService(client, _Embedder())  # type: ignore[arg-type]
    tenant_id, course_id, version_id = uuid.uuid4(), uuid.uuid4(), uuid.uuid4()
    result = await service.search(
        "question",
        tenant_id=tenant_id,
        course_id=course_id,
        content_version_id=version_id,
        access_label=rank,
    )
    assert {item.text for item in result.candidates} == visible
    dumped = client.filter.model_dump(mode="json")
    assert str(tenant_id) in str(dumped)
    assert str(course_id) in str(dumped)
    assert str(version_id) in str(dumped)
    # MatchAny is present in the pre-ranking filter; exact content is verified by text.
    assert "access_label" in str(dumped)
