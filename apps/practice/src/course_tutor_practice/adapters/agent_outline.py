"""HTTP adapter for Agent's versioned textbook-outline operation."""

from __future__ import annotations

from uuid import UUID

import httpx

from course_tutor_contracts import CatalogBookOutline
from course_tutor_practice.adapters.agent_client import AgentCatalogError


class HttpAgentOutlineProvider:
    def __init__(self, base_url: str) -> None:
        self._client = httpx.AsyncClient(base_url=base_url.rstrip("/"), timeout=10.0)

    async def get_outline(
        self,
        book_id: UUID,
        content_version_id: UUID,
        bearer: str,
        correlation_id: str | None,
    ) -> CatalogBookOutline:
        headers = {"Authorization": bearer}
        if correlation_id:
            headers["X-Correlation-ID"] = correlation_id
        try:
            response = await self._client.get(
                f"/v1/catalog/books/{book_id}/outline",
                params={"content_version_id": str(content_version_id)},
                headers=headers,
            )
        except httpx.HTTPError as exc:
            raise AgentCatalogError(503, "Agent outline is unavailable") from exc
        if response.status_code == 404:
            return CatalogBookOutline(
                book_id=book_id,
                content_version_id=content_version_id,
                availability="unavailable",
                extractor_version="agent-v1",
                provenance="none",
                confidence=0,
                reason="outline not available",
            )
        if response.is_error:
            raise AgentCatalogError(response.status_code, "Agent outline request failed")
        return CatalogBookOutline.model_validate(response.json())

    async def aclose(self) -> None:
        await self._client.aclose()
