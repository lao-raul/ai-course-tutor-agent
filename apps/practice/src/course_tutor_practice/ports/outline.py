"""Versioned Agent outline boundary used to build deterministic default plans."""

from __future__ import annotations

from typing import Protocol
from uuid import UUID

from course_tutor_contracts import CatalogBookOutline


class OutlineProvider(Protocol):
    async def get_outline(
        self,
        book_id: UUID,
        content_version_id: UUID,
        bearer: str,
        correlation_id: str | None,
    ) -> CatalogBookOutline: ...


class UnavailableOutlineProvider:
    """Safe fallback while TASK-24's Agent endpoint is unavailable."""

    async def get_outline(
        self,
        book_id: UUID,
        content_version_id: UUID,
        _bearer: str,
        _correlation_id: str | None,
    ) -> CatalogBookOutline:
        return CatalogBookOutline(
            book_id=book_id,
            content_version_id=content_version_id,
            availability="unavailable",
            extractor_version="unavailable-v1",
            provenance="none",
            confidence=0,
            reason="outline provider unavailable",
        )
