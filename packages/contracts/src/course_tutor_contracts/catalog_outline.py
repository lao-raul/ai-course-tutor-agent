"""Stable, bounded textbook-outline DTOs shared with Hiruzen."""

from __future__ import annotations

from typing import Literal
from uuid import UUID

from pydantic import Field

from course_tutor_contracts.catalog import CatalogModel


class CatalogOutlineNode(CatalogModel):
    id: str = Field(min_length=1, max_length=96)
    parent_id: str | None = Field(default=None, max_length=96)
    ordinal: int = Field(ge=0)
    title: str = Field(min_length=1, max_length=300)
    page_start: int = Field(ge=1)
    page_end: int | None = Field(default=None, ge=1)
    depth: int = Field(ge=0, le=8)


class CatalogBookOutline(CatalogModel):
    book_id: UUID
    content_version_id: UUID
    availability: Literal["available", "unavailable"]
    extractor_version: str = Field(min_length=1, max_length=64)
    provenance: Literal["pdf_bookmarks", "text_toc", "heading_rules", "ocr", "none"]
    confidence: float = Field(ge=0, le=1)
    reason: str | None = Field(default=None, max_length=300)
    nodes: tuple[CatalogOutlineNode, ...] = ()
