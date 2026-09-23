"""content addressed sources and controlled automatic ingestion

Revision ID: f31b8d02c913
Revises: a41c9e7d2b60
"""

from collections.abc import Sequence

import sqlalchemy as sa
from alembic import op

revision: str = "f31b8d02c913"
down_revision: str | None = "a41c9e7d2b60"
branch_labels: str | Sequence[str] | None = None
depends_on: str | Sequence[str] | None = None


def upgrade() -> None:
    op.add_column(
        "source_roots",
        sa.Column(
            "automatic_ingestion_enabled",
            sa.Boolean(),
            server_default=sa.true(),
            nullable=False,
        ),
    )
    op.create_table(
        "content_version_sources",
        sa.Column("version_id", sa.UUID(), nullable=False),
        sa.Column("source_id", sa.UUID(), nullable=False),
        sa.ForeignKeyConstraint(["source_id"], ["source_documents.id"], ondelete="CASCADE"),
        sa.ForeignKeyConstraint(["version_id"], ["content_versions.id"], ondelete="CASCADE"),
        sa.PrimaryKeyConstraint("version_id", "source_id"),
    )
    op.execute(
        sa.text(
            """
            INSERT INTO content_version_sources (version_id, source_id)
            SELECT version_id, id FROM source_documents
            ON CONFLICT DO NOTHING
            """
        )
    )
    op.alter_column("source_roots", "automatic_ingestion_enabled", server_default=None)


def downgrade() -> None:
    op.drop_table("content_version_sources")
    op.drop_column("source_roots", "automatic_ingestion_enabled")
