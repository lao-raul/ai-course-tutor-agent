"""agent memory and persisted chat turns

Revision ID: a41c9e7d2b60
Revises: 8d90c87b7341
"""

from collections.abc import Sequence

import sqlalchemy as sa
from alembic import op

revision: str = "a41c9e7d2b60"
down_revision: str | None = "8d90c87b7341"
branch_labels: str | Sequence[str] | None = None
depends_on: str | Sequence[str] | None = None


def upgrade() -> None:
    op.create_table(
        "memory_settings",
        sa.Column("id", sa.UUID(), nullable=False),
        sa.Column("user_id", sa.UUID(), nullable=False),
        sa.Column("course_id", sa.UUID(), nullable=False),
        sa.Column("enabled", sa.Boolean(), nullable=False),
        sa.Column("created_at", sa.DateTime(), server_default=sa.func.now(), nullable=False),
        sa.Column("updated_at", sa.DateTime(), server_default=sa.func.now(), nullable=False),
        sa.ForeignKeyConstraint(["course_id"], ["courses.id"], ondelete="CASCADE"),
        sa.ForeignKeyConstraint(["user_id"], ["users.id"], ondelete="CASCADE"),
        sa.PrimaryKeyConstraint("id"),
        sa.UniqueConstraint("user_id", "course_id"),
    )
    op.create_table(
        "chat_turns",
        sa.Column("id", sa.UUID(), nullable=False),
        sa.Column("session_id", sa.UUID(), nullable=False),
        sa.Column("role", sa.String(16), nullable=False),
        sa.Column("content", sa.Text(), nullable=False),
        sa.Column("token_count", sa.Integer(), nullable=False),
        sa.Column("created_at", sa.DateTime(), server_default=sa.func.now(), nullable=False),
        sa.Column("updated_at", sa.DateTime(), server_default=sa.func.now(), nullable=False),
        sa.CheckConstraint("role IN ('user', 'assistant')", name="role_known"),
        sa.CheckConstraint("token_count >= 0", name="token_count_non_negative"),
        sa.ForeignKeyConstraint(["session_id"], ["chat_sessions.id"], ondelete="CASCADE"),
        sa.PrimaryKeyConstraint("id"),
    )
    op.create_index("ix_chat_turns_session_created", "chat_turns", ["session_id", "created_at"])

    op.drop_constraint("uq_memory_facts_user_id", "memory_facts", type_="unique")
    op.create_index(
        "uq_memory_facts_active_key",
        "memory_facts",
        ["user_id", "course_id", "type", "normalized_key"],
        unique=True,
        postgresql_where=sa.text("status = 'active'"),
    )


def downgrade() -> None:
    op.drop_index("uq_memory_facts_active_key", table_name="memory_facts")
    op.create_unique_constraint(
        "uq_memory_facts_user_id",
        "memory_facts",
        ["user_id", "course_id", "type", "normalized_key"],
    )
    op.drop_index("ix_chat_turns_session_created", table_name="chat_turns")
    op.drop_table("chat_turns")
    op.drop_table("memory_settings")
