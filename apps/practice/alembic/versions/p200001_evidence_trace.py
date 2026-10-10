"""Persist Agent retrieval trace IDs on generated PracticeSets.

Revision ID: p200001
Revises: p190001
"""

from collections.abc import Sequence

import sqlalchemy as sa
from alembic import op

revision: str = "p200001"
down_revision: str | None = "p190001"
branch_labels: str | Sequence[str] | None = None
depends_on: str | Sequence[str] | None = None


def upgrade() -> None:
    op.add_column(
        "practice_sets",
        sa.Column("retrieval_trace_id", sa.UUID(), nullable=True),
        schema="practice",
    )


def downgrade() -> None:
    op.drop_column("practice_sets", "retrieval_trace_id", schema="practice")
