"""Persist redacted instructor preview access events."""

from collections.abc import Sequence

import sqlalchemy as sa
from alembic import op
from sqlalchemy.dialects.postgresql import UUID

revision: str = "p250001"
down_revision: str | None = "p220001"
branch_labels: str | Sequence[str] | None = None
depends_on: str | Sequence[str] | None = None


def upgrade() -> None:
    op.create_table(
        "preview_audits",
        sa.Column("id", UUID(as_uuid=True), primary_key=True),
        sa.Column("tenant_id", UUID(as_uuid=True), nullable=False),
        sa.Column("actor_id", UUID(as_uuid=True), nullable=False),
        sa.Column("set_id", UUID(as_uuid=True), nullable=False),
        sa.Column("content_version_id", UUID(as_uuid=True), nullable=False),
        sa.Column("correlation_id", sa.String(255), nullable=False),
        sa.Column("created_at", sa.DateTime(), server_default=sa.func.now(), nullable=False),
        schema="practice",
    )


def downgrade() -> None:
    op.drop_table("preview_audits", schema="practice")
