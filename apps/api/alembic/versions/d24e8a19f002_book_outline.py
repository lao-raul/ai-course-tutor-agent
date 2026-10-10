"""Versioned deterministic textbook outlines.

Revision ID: d24e8a19f002
Revises: c7e13a09d4f2
"""

from collections.abc import Sequence

import sqlalchemy as sa
from alembic import op
from sqlalchemy.dialects import postgresql

revision: str = "d24e8a19f002"
down_revision: str | None = "c7e13a09d4f2"
branch_labels: str | Sequence[str] | None = None
depends_on: str | Sequence[str] | None = None


def upgrade() -> None:
    op.create_table(
        "book_outlines",
        sa.Column("id", sa.UUID(), nullable=False),
        sa.Column("book_id", sa.UUID(), nullable=False),
        sa.Column("content_version_id", sa.UUID(), nullable=False),
        sa.Column("source_id", sa.UUID(), nullable=True),
        sa.Column("extractor_version", sa.String(length=64), nullable=False),
        sa.Column("availability", sa.String(length=16), nullable=False),
        sa.Column("provenance", sa.String(length=32), nullable=False),
        sa.Column("confidence", sa.Float(), nullable=False),
        sa.Column("reason", sa.String(length=300), nullable=True),
        sa.Column("nodes", postgresql.JSONB(astext_type=sa.Text()), nullable=False),
        sa.Column("created_at", sa.DateTime(), server_default=sa.func.now(), nullable=False),
        sa.Column("updated_at", sa.DateTime(), server_default=sa.func.now(), nullable=False),
        sa.CheckConstraint(
            "confidence >= 0 AND confidence <= 1", name="book_outline_confidence_range"
        ),
        sa.CheckConstraint(
            "availability IN ('available', 'unavailable')",
            name="book_outline_availability_known",
        ),
        sa.CheckConstraint(
            "provenance IN ('pdf_bookmarks', 'text_toc', 'heading_rules', 'ocr', 'none')",
            name="book_outline_provenance_known",
        ),
        sa.ForeignKeyConstraint(["book_id"], ["books.id"], ondelete="CASCADE"),
        sa.ForeignKeyConstraint(
            ["content_version_id"], ["content_versions.id"], ondelete="CASCADE"
        ),
        sa.ForeignKeyConstraint(["source_id"], ["source_documents.id"], ondelete="SET NULL"),
        sa.PrimaryKeyConstraint("id"),
        sa.UniqueConstraint("book_id", "content_version_id", name="uq_book_outline_version"),
    )
    op.create_index(
        "ix_book_outlines_book_version", "book_outlines", ["book_id", "content_version_id"]
    )


def downgrade() -> None:
    op.drop_index("ix_book_outlines_book_version", table_name="book_outlines")
    op.drop_table("book_outlines")
