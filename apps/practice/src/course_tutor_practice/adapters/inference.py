"""OpenAI-compatible structured inference without a second RAG implementation."""

from __future__ import annotations

import httpx

from course_tutor_practice.generation.errors import GenerationFailure
from course_tutor_practice.generation.schemas import GeneratedBatch


class OpenAICompatiblePracticeInference:
    def __init__(
        self,
        base_url: str,
        model: str,
        api_key: str,
        client: httpx.AsyncClient | None = None,
    ) -> None:
        self.model = model
        self._owns_client = client is None
        self._client = client or httpx.AsyncClient(
            base_url=base_url.rstrip("/"),
            headers={"Authorization": f"Bearer {api_key}"},
            timeout=httpx.Timeout(connect=5, read=120, write=10, pool=5),
        )

    async def generate_json(
        self, messages: list[dict[str, str]], seed: int, correlation_id: str
    ) -> str:
        try:
            response = await self._client.post(
                "/chat/completions",
                headers={"X-Correlation-ID": correlation_id},
                json={
                    "model": self.model,
                    "messages": messages,
                    "temperature": 0.1,
                    "seed": seed,
                    "response_format": {
                        "type": "json_schema",
                        "json_schema": {
                            "name": "hiruzen_generated_batch_v1",
                            "schema": GeneratedBatch.model_json_schema(),
                        },
                    },
                    "stream": False,
                },
            )
            response.raise_for_status()
            message = response.json()["choices"][0]["message"]
            content = message["content"] or message.get("reasoning_content")
            if not isinstance(content, str) or len(content) > 131_072:
                raise GenerationFailure("invalid_model_response")
            return content
        except httpx.RequestError as exc:
            raise GenerationFailure("inference_unavailable", retryable=True) from exc
        except httpx.HTTPStatusError as exc:
            retryable = exc.response.status_code == 429 or exc.response.status_code >= 500
            raise GenerationFailure("inference_unavailable", retryable=retryable) from exc
        except (KeyError, IndexError, TypeError, ValueError) as exc:
            raise GenerationFailure("invalid_model_response") from exc

    async def aclose(self) -> None:
        if self._owns_client:
            await self._client.aclose()
