"""Keep accepted learning objectives for same-book cross-job diversity.

Revision ID: p220001
Revises: p210001
"""

from collections.abc import Sequence

import sqlalchemy as sa
from alembic import op
from sqlalchemy.dialects import postgresql

revision: str = "p220001"
down_revision: str | None = "p210001"
branch_labels: str | Sequence[str] | None = None
depends_on: str | Sequence[str] | None = None


def upgrade() -> None:
    op.add_column(
        "practice_sets",
        sa.Column(
            "objective_metadata",
            postgresql.JSONB(),
            nullable=False,
            server_default=sa.text("'[]'::jsonb"),
        ),
        schema="practice",
    )
    op.create_index(
        "ix_practice_sets_objective_history",
        "practice_sets",
        ["tenant_id", "user_id", "agent_book_id", "agent_content_version_id", "created_at"],
        schema="practice",
    )


def downgrade() -> None:
    op.drop_index(
        "ix_practice_sets_objective_history", table_name="practice_sets", schema="practice"
    )
    op.drop_column("practice_sets", "objective_metadata", schema="practice")
