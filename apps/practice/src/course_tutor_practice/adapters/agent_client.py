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
    PracticeEvidenceRequest,
    PracticeEvidenceResponse,
)
from course_tutor_practice.generation.errors import GenerationFailure


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


class HttpAgentEvidenceProvider:
    def __init__(self, base_url: str, client: httpx.AsyncClient | None = None) -> None:
        self._owns_client = client is None
        self._client = client or httpx.AsyncClient(base_url=base_url.rstrip("/"), timeout=20.0)

    async def retrieve(
        self, request: PracticeEvidenceRequest, delegation_token: str, correlation_id: str
    ) -> PracticeEvidenceResponse:
        try:
            response = await self._client.post(
                "/v1/internal/practice/evidence:retrieve",
                json=request.model_dump(mode="json"),
                headers={
                    "Authorization": f"Bearer {delegation_token}",
                    "X-Correlation-ID": correlation_id,
                },
            )
        except httpx.HTTPError as exc:
            raise GenerationFailure("evidence_unavailable", retryable=True) from exc
        if response.status_code in {401, 403, 404, 409}:
            raise GenerationFailure("evidence_access_denied")
        if response.is_error:
            raise GenerationFailure(
                "evidence_unavailable",
                retryable=response.status_code >= 500 or response.status_code == 429,
            )
        try:
            evidence = PracticeEvidenceResponse.model_validate(response.json())
        except (ValueError, TypeError) as exc:
            raise GenerationFailure("invalid_evidence_response") from exc
        if (
            evidence.generation_id != request.generation_id
            or evidence.book_id != request.book_id
            or evidence.course_id != request.course_id
            or evidence.content_version_id != request.content_version_id
        ):
            raise GenerationFailure("evidence_scope_mismatch")
        return evidence

    async def aclose(self) -> None:
        if self._owns_client:
            await self._client.aclose()
