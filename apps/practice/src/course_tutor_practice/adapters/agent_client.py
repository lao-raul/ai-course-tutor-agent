"""HTTP-only Agent catalog adapter; Hiruzen never imports Agent internals."""

from __future__ import annotations

from typing import Any, Protocol
from uuid import UUID

import httpx

from course_tutor_contracts import (
    CatalogBookDetail,
    CatalogBookPage,
    CatalogCategoryView,
    CatalogCourseView,
)


class AgentCatalogError(RuntimeError):
    def __init__(self, status_code: int, detail: str) -> None:
        super().__init__(detail)
        self.status_code = status_code
        self.detail = detail


class AgentCatalogClient(Protocol):
    async def list_categories(
        self, bearer: str, correlation_id: str | None
    ) -> list[CatalogCategoryView]: ...

    async def search_books(
        self,
        bearer: str,
        correlation_id: str | None,
        params: dict[str, Any],
    ) -> CatalogBookPage: ...

    async def get_book(
        self, book_id: UUID, bearer: str, correlation_id: str | None
    ) -> CatalogBookDetail: ...

    async def list_book_courses(
        self, book_id: UUID, bearer: str, correlation_id: str | None
    ) -> list[CatalogCourseView]: ...


class HttpAgentCatalogClient:
    def __init__(self, base_url: str) -> None:
        self._client = httpx.AsyncClient(base_url=base_url.rstrip("/"), timeout=10.0)

    async def _get(
        self,
        path: str,
        bearer: str,
        correlation_id: str | None,
        *,
        params: dict[str, Any] | None = None,
    ) -> Any:
        headers = {"Authorization": bearer}
        if correlation_id:
            headers["X-Correlation-ID"] = correlation_id
        try:
            response = await self._client.get(path, headers=headers, params=params)
        except httpx.HTTPError as exc:
            raise AgentCatalogError(503, "Agent catalog is unavailable") from exc
        if response.is_error:
            try:
                detail = str(response.json().get("detail", "Agent catalog request failed"))
            except (ValueError, AttributeError):
                detail = "Agent catalog request failed"
            raise AgentCatalogError(response.status_code, detail)
        return response.json()

    async def list_categories(
        self, bearer: str, correlation_id: str | None
    ) -> list[CatalogCategoryView]:
        payload = await self._get("/v1/catalog/categories", bearer, correlation_id)
        return [CatalogCategoryView.model_validate(item) for item in payload]

    async def search_books(
        self,
        bearer: str,
        correlation_id: str | None,
        params: dict[str, Any],
    ) -> CatalogBookPage:
        payload = await self._get("/v1/catalog/books", bearer, correlation_id, params=params)
        return CatalogBookPage.model_validate(payload)

    async def get_book(
        self, book_id: UUID, bearer: str, correlation_id: str | None
    ) -> CatalogBookDetail:
        payload = await self._get(f"/v1/catalog/books/{book_id}", bearer, correlation_id)
        return CatalogBookDetail.model_validate(payload)

    async def list_book_courses(
        self, book_id: UUID, bearer: str, correlation_id: str | None
    ) -> list[CatalogCourseView]:
        payload = await self._get(f"/v1/catalog/books/{book_id}/courses", bearer, correlation_id)
        return [CatalogCourseView.model_validate(item) for item in payload]

    async def aclose(self) -> None:
        await self._client.aclose()


__all__ = ["AgentCatalogClient", "AgentCatalogError", "HttpAgentCatalogClient"]
