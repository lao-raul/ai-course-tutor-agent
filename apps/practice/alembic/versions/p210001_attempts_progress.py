"""Immutable attempts, activity, progress, resume, reports and consent.

Revision ID: p210001
Revises: p200001
"""

from collections.abc import Sequence

import sqlalchemy as sa
from alembic import op
from sqlalchemy.dialects import postgresql

revision: str = "p210001"
down_revision: str | None = "p200001"
branch_labels: str | Sequence[str] | None = None
depends_on: str | Sequence[str] | None = None


def _created() -> sa.Column:
    return sa.Column(
        "created_at", sa.DateTime(timezone=True), server_default=sa.func.now(), nullable=False
    )


def _updated() -> sa.Column:
    return sa.Column(
        "updated_at", sa.DateTime(timezone=True), server_default=sa.func.now(), nullable=False
    )


def upgrade() -> None:
    op.create_table(
        "attempts",
        sa.Column("id", sa.UUID(), primary_key=True),
        sa.Column("tenant_id", sa.UUID(), nullable=False),
        sa.Column("user_id", sa.UUID(), nullable=False),
        sa.Column(
            "practice_set_id", sa.UUID(), sa.ForeignKey("practice.practice_sets.id"), nullable=False
        ),
        sa.Column("exercise_id", sa.UUID(), sa.ForeignKey("practice.exercises.id"), nullable=False),
        sa.Column("attempt_number", sa.Integer(), nullable=False),
        sa.Column("action", sa.String(16), nullable=False),
        sa.Column("idempotency_key", sa.String(255), nullable=False),
        sa.Column("request_digest", sa.String(64), nullable=False),
        sa.Column("submitted_value", postgresql.JSONB()),
        sa.Column("correct", sa.Boolean()),
        sa.Column("score", sa.Float()),
        sa.Column("provisional", sa.Boolean(), nullable=False),
        sa.Column("evaluator", sa.String(64), nullable=False),
        sa.Column("evaluator_version", sa.String(255), nullable=False),
        _created(),
        sa.UniqueConstraint(
            "tenant_id",
            "user_id",
            "exercise_id",
            "idempotency_key",
            name="uq_attempt_idempotency",
        ),
        sa.UniqueConstraint(
            "tenant_id",
            "user_id",
            "exercise_id",
            "attempt_number",
            name="uq_attempt_ordinal",
        ),
        sa.CheckConstraint("attempt_number BETWEEN 1 AND 4", name="attempt_number_range"),
        sa.CheckConstraint("action IN ('submit','give_up')", name="attempt_action_known"),
        schema="practice",
    )
    op.create_index(
        "ix_attempts_owner_set",
        "attempts",
        ["tenant_id", "user_id", "practice_set_id"],
        schema="practice",
    )
    op.create_table(
        "study_activity",
        sa.Column("id", sa.UUID(), primary_key=True),
        sa.Column("tenant_id", sa.UUID(), nullable=False),
        sa.Column("user_id", sa.UUID(), nullable=False),
        sa.Column("practice_set_id", sa.UUID(), sa.ForeignKey("practice.practice_sets.id")),
        sa.Column("exercise_id", sa.UUID(), sa.ForeignKey("practice.exercises.id")),
        sa.Column("event_type", sa.String(32), nullable=False),
        sa.Column("source_key", sa.String(255), nullable=False),
        _created(),
        sa.UniqueConstraint("tenant_id", "user_id", "source_key"),
        schema="practice",
    )
    op.create_index(
        "ix_study_activity_owner_set",
        "study_activity",
        ["tenant_id", "user_id", "practice_set_id"],
        schema="practice",
    )
    op.create_table(
        "study_progress",
        sa.Column("id", sa.UUID(), primary_key=True),
        sa.Column("tenant_id", sa.UUID(), nullable=False),
        sa.Column("user_id", sa.UUID(), nullable=False),
        sa.Column(
            "practice_set_id", sa.UUID(), sa.ForeignKey("practice.practice_sets.id"), nullable=False
        ),
        sa.Column("status", sa.String(16), nullable=False),
        sa.Column("total_questions", sa.Integer(), nullable=False),
        sa.Column("attempted_questions", sa.Integer(), nullable=False),
        sa.Column("completed_questions", sa.Integer(), nullable=False),
        sa.Column("correct_questions", sa.Integer(), nullable=False),
        sa.Column("next_exercise_id", sa.UUID()),
        sa.Column("latest_activity_at", sa.DateTime(timezone=True)),
        sa.Column("topic_mastery", postgresql.JSONB(), nullable=False),
        _created(),
        _updated(),
        sa.UniqueConstraint("tenant_id", "user_id", "practice_set_id"),
        schema="practice",
    )
    op.create_table(
        "resume_cursors",
        sa.Column("id", sa.UUID(), primary_key=True),
        sa.Column("tenant_id", sa.UUID(), nullable=False),
        sa.Column("user_id", sa.UUID(), nullable=False),
        sa.Column("practice_set_id", sa.UUID(), sa.ForeignKey("practice.practice_sets.id")),
        sa.Column("exercise_id", sa.UUID()),
        sa.Column("cleared", sa.Boolean(), nullable=False),
        _created(),
        _updated(),
        sa.UniqueConstraint("tenant_id", "user_id"),
        schema="practice",
    )
    op.create_table(
        "exercise_reports",
        sa.Column("id", sa.UUID(), primary_key=True),
        sa.Column("tenant_id", sa.UUID(), nullable=False),
        sa.Column("user_id", sa.UUID(), nullable=False),
        sa.Column("exercise_id", sa.UUID(), sa.ForeignKey("practice.exercises.id"), nullable=False),
        sa.Column("idempotency_key", sa.String(255), nullable=False),
        sa.Column("reason", sa.String(32), nullable=False),
        sa.Column("detail", sa.Text(), nullable=False),
        sa.Column("status", sa.String(16), nullable=False),
        _created(),
        sa.UniqueConstraint("tenant_id", "user_id", "exercise_id", "idempotency_key"),
        schema="practice",
    )
    op.create_table(
        "study_memory_consent",
        sa.Column("id", sa.UUID(), primary_key=True),
        sa.Column("tenant_id", sa.UUID(), nullable=False),
        sa.Column("user_id", sa.UUID(), nullable=False),
        sa.Column("enabled", sa.Boolean(), nullable=False),
        _created(),
        _updated(),
        sa.UniqueConstraint("tenant_id", "user_id"),
        schema="practice",
    )
    op.execute("""
        CREATE FUNCTION practice.reject_immutable_study_write() RETURNS trigger
        LANGUAGE plpgsql AS $$
        BEGIN RAISE EXCEPTION 'immutable study record'; END;
        $$;
    """)
    for table in ("attempts", "study_activity"):
        op.execute(
            f"CREATE TRIGGER reject_immutable_write BEFORE UPDATE OR DELETE ON practice.{table} "
            "FOR EACH ROW EXECUTE FUNCTION practice.reject_immutable_study_write()"
        )


def downgrade() -> None:
    for table in ("attempts", "study_activity"):
        op.execute(f"DROP TRIGGER reject_immutable_write ON practice.{table}")
    op.execute("DROP FUNCTION practice.reject_immutable_study_write()")
    for table in (
        "study_memory_consent",
        "exercise_reports",
        "resume_cursors",
        "study_progress",
        "study_activity",
        "attempts",
    ):
        op.drop_table(table, schema="practice")
