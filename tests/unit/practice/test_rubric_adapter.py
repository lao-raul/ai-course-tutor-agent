"""The local LM Studio rubric scorer must work without an API key."""

from __future__ import annotations

import json

import httpx
import pytest

from course_tutor_practice.adapters.rubric import OpenAICompatibleRubricEvaluator


@pytest.mark.asyncio
async def test_rubric_scorer_omits_authorization_for_empty_local_key() -> None:
    requests: list[httpx.Request] = []

    def respond(request: httpx.Request) -> httpx.Response:
        requests.append(request)
        return httpx.Response(
            200,
            json={"choices": [{"message": {"content": '{"criterion_scores":[0.9]}'}}]},
        )

    evaluator = OpenAICompatibleRubricEvaluator(
        "http://localhost:1234/v1",
        "local-chat",
        "",
        transport=httpx.MockTransport(respond),
    )
    try:
        scores = await evaluator.score(
            answer="Hello is a greeting.",
            exemplar="Hello is a greeting.",
            criteria=("Names the greeting",),
            correlation_id="test-correlation",
        )
    finally:
        await evaluator.aclose()
    assert scores == (0.9,)
    assert len(requests) == 1
    assert "authorization" not in requests[0].headers
    assert requests[0].headers["x-correlation-id"] == "test-correlation"
    assert json.loads(requests[0].content)["model"] == "local-chat"


@pytest.mark.asyncio
async def test_rubric_scorer_keeps_nonempty_api_key() -> None:
    def respond(request: httpx.Request) -> httpx.Response:
        assert request.headers["authorization"] == "Bearer test-key"
        return httpx.Response(
            200,
            json={"choices": [{"message": {"content": '{"criterion_scores":[1.0]}'}}]},
        )

    evaluator = OpenAICompatibleRubricEvaluator(
        "http://localhost:1234/v1",
        "local-chat",
        "test-key",
        transport=httpx.MockTransport(respond),
    )
    try:
        assert await evaluator.score(
            answer="Hello",
            exemplar="Hello",
            criteria=("Greeting",),
            correlation_id="test-correlation",
        ) == (1.0,)
    finally:
        await evaluator.aclose()


@pytest.mark.asyncio
async def test_rubric_scorer_still_fails_closed_on_invalid_result() -> None:
    evaluator = OpenAICompatibleRubricEvaluator(
        "http://localhost:1234/v1",
        "local-chat",
        "",
        transport=httpx.MockTransport(
            lambda request: httpx.Response(
                200,
                json={"choices": [{"message": {"content": '{"criterion_scores":[2.0]}'}}]},
            )
        ),
    )
    try:
        with pytest.raises(RuntimeError, match="short-answer evaluator is unavailable"):
            await evaluator.score(
                answer="Hello",
                exemplar="Hello",
                criteria=("Greeting",),
                correlation_id="test-correlation",
            )
    finally:
        await evaluator.aclose()
