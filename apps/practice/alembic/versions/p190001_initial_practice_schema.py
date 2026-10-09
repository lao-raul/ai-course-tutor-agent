"""Initial Hiruzen practice schema and generation outbox.

Revision ID: p190001
Revises:
"""

from collections.abc import Sequence

import sqlalchemy as sa
from alembic import op
from sqlalchemy.dialects import postgresql

revision: str = "p190001"
down_revision: str | None = None
branch_labels: str | Sequence[str] | None = None
depends_on: str | Sequence[str] | None = None


def _timestamps() -> tuple[sa.Column, sa.Column]:
    return (
        sa.Column("created_at", sa.DateTime(), server_default=sa.func.now(), nullable=False),
        sa.Column("updated_at", sa.DateTime(), server_default=sa.func.now(), nullable=False),
    )


def upgrade() -> None:
    op.execute("CREATE SCHEMA IF NOT EXISTS practice")
    op.create_table(
        "study_plans",
        sa.Column("id", sa.UUID(), nullable=False),
        sa.Column("tenant_id", sa.UUID(), nullable=False),
        sa.Column("agent_book_id", sa.UUID(), nullable=False),
        sa.Column("agent_course_id", sa.UUID(), nullable=False),
        sa.Column("agent_course_run_id", sa.UUID(), nullable=False),
        sa.Column("agent_content_version_id", sa.UUID(), nullable=False),
        sa.Column("name", sa.String(500), nullable=False),
        sa.Column("revision", sa.Integer(), nullable=False),
        sa.Column("policy", postgresql.JSONB(), nullable=False),
        *_timestamps(),
        sa.PrimaryKeyConstraint("id"),
        sa.UniqueConstraint(
            "tenant_id",
            "agent_book_id",
            "agent_content_version_id",
            name="uq_study_plan_book_content_version",
        ),
        schema="practice",
    )
    op.create_index(
        "ix_study_plans_tenant_book",
        "study_plans",
        ["tenant_id", "agent_book_id"],
        schema="practice",
    )
    op.create_table(
        "study_plan_modules",
        sa.Column("id", sa.UUID(), nullable=False),
        sa.Column("study_plan_id", sa.UUID(), nullable=False),
        sa.Column("ordinal", sa.Integer(), nullable=False),
        sa.Column("title", sa.String(500), nullable=False),
        sa.Column("outline_node_id", sa.String(96)),
        sa.Column("objectives", postgresql.JSONB(), nullable=False),
        *_timestamps(),
        sa.ForeignKeyConstraint(["study_plan_id"], ["practice.study_plans.id"], ondelete="CASCADE"),
        sa.PrimaryKeyConstraint("id"),
        sa.UniqueConstraint("study_plan_id", "ordinal", name="uq_study_plan_module_ordinal"),
        schema="practice",
    )
    op.create_table(
        "generation_jobs",
        sa.Column("id", sa.UUID(), nullable=False),
        sa.Column("tenant_id", sa.UUID(), nullable=False),
        sa.Column("user_id", sa.UUID(), nullable=False),
        sa.Column("study_plan_id", sa.UUID(), nullable=False),
        sa.Column("module_id", sa.UUID()),
        sa.Column("agent_book_id", sa.UUID(), nullable=False),
        sa.Column("agent_course_id", sa.UUID(), nullable=False),
        sa.Column("agent_course_run_id", sa.UUID(), nullable=False),
        sa.Column("agent_content_version_id", sa.UUID(), nullable=False),
        sa.Column("idempotency_key", sa.String(255), nullable=False),
        sa.Column("request_payload", postgresql.JSONB(), nullable=False),
        sa.Column("requested_count", sa.Integer(), nullable=False),
        sa.Column("status", sa.String(16), nullable=False),
        sa.Column("correlation_id", sa.String(64), nullable=False),
        sa.Column("deadline_at", sa.DateTime(timezone=True), nullable=False),
        sa.Column("attempt_count", sa.Integer(), nullable=False),
        sa.Column("lease_owner", sa.String(128)),
        sa.Column("lease_expires_at", sa.DateTime(timezone=True)),
        sa.Column("error_code", sa.String(64)),
        sa.Column("error_detail", sa.Text()),
        sa.Column("retryable", sa.Boolean()),
        *_timestamps(),
        sa.CheckConstraint(
            "status IN ('queued','retrieving','generating','validating','ready','failed','cancelled')",
            name="generation_status_known",
        ),
        sa.CheckConstraint("requested_count BETWEEN 1 AND 20", name="generation_count_range"),
        sa.ForeignKeyConstraint(
            ["study_plan_id"], ["practice.study_plans.id"], ondelete="RESTRICT"
        ),
        sa.ForeignKeyConstraint(
            ["module_id"], ["practice.study_plan_modules.id"], ondelete="RESTRICT"
        ),
        sa.PrimaryKeyConstraint("id"),
        sa.UniqueConstraint(
            "tenant_id", "user_id", "idempotency_key", name="uq_generation_idempotency"
        ),
        schema="practice",
    )
    op.create_index(
        "ix_generation_jobs_owner",
        "generation_jobs",
        ["tenant_id", "user_id", "created_at"],
        schema="practice",
    )
    op.create_index(
        "ix_generation_jobs_status_deadline",
        "generation_jobs",
        ["status", "deadline_at"],
        schema="practice",
    )
    op.create_table(
        "practice_sets",
        sa.Column("id", sa.UUID(), nullable=False),
        sa.Column("generation_job_id", sa.UUID(), nullable=False),
        sa.Column("tenant_id", sa.UUID(), nullable=False),
        sa.Column("user_id", sa.UUID(), nullable=False),
        sa.Column("study_plan_id", sa.UUID(), nullable=False),
        sa.Column("agent_book_id", sa.UUID(), nullable=False),
        sa.Column("agent_course_id", sa.UUID(), nullable=False),
        sa.Column("agent_content_version_id", sa.UUID(), nullable=False),
        sa.Column("seed", sa.Integer(), nullable=False),
        sa.Column("prompt_version", sa.String(64), nullable=False),
        sa.Column("model_version", sa.String(255), nullable=False),
        sa.Column("validator_version", sa.String(64), nullable=False),
        sa.Column("evidence_chunk_ids", postgresql.JSONB(), nullable=False),
        sa.Column("correlation_id", sa.String(64), nullable=False),
        *_timestamps(),
        sa.ForeignKeyConstraint(
            ["generation_job_id"], ["practice.generation_jobs.id"], ondelete="RESTRICT"
        ),
        sa.ForeignKeyConstraint(
            ["study_plan_id"], ["practice.study_plans.id"], ondelete="RESTRICT"
        ),
        sa.PrimaryKeyConstraint("id"),
        sa.UniqueConstraint("generation_job_id"),
        schema="practice",
    )
    op.create_table(
        "exercises",
        sa.Column("id", sa.UUID(), nullable=False),
        sa.Column("practice_set_id", sa.UUID(), nullable=False),
        sa.Column("ordinal", sa.Integer(), nullable=False),
        sa.Column("question_type", sa.String(32), nullable=False),
        sa.Column("presentation", postgresql.JSONB(), nullable=False),
        sa.Column("protected_answer", postgresql.JSONB(), nullable=False),
        sa.Column("rationale", sa.Text(), nullable=False),
        sa.Column("evidence_citation_ids", postgresql.JSONB(), nullable=False),
        sa.Column("fingerprint", sa.String(64), nullable=False),
        *_timestamps(),
        sa.CheckConstraint(
            "question_type IN ('multiple_choice','true_false','fill_in_the_blank','short_answer')",
            name="exercise_type_known",
        ),
        sa.ForeignKeyConstraint(
            ["practice_set_id"], ["practice.practice_sets.id"], ondelete="CASCADE"
        ),
        sa.PrimaryKeyConstraint("id"),
        sa.UniqueConstraint("practice_set_id", "ordinal"),
        schema="practice",
    )
    op.create_index(
        "ix_practice_exercises_fingerprint",
        "exercises",
        ["fingerprint"],
        schema="practice",
    )
    op.create_table(
        "outbox_events",
        sa.Column("id", sa.UUID(), nullable=False),
        sa.Column("generation_job_id", sa.UUID(), nullable=False),
        sa.Column("topic", sa.String(128), nullable=False),
        sa.Column("idempotency_key", sa.String(255), nullable=False),
        sa.Column("payload", postgresql.JSONB(), nullable=False),
        sa.Column("correlation_id", sa.String(64), nullable=False),
        sa.Column("attempts", sa.Integer(), nullable=False),
        sa.Column("lease_owner", sa.String(128)),
        sa.Column("lease_expires_at", sa.DateTime(timezone=True)),
        sa.Column("processed_at", sa.DateTime(timezone=True)),
        sa.Column("dead_lettered_at", sa.DateTime(timezone=True)),
        sa.Column("last_error", sa.Text()),
        *_timestamps(),
        sa.ForeignKeyConstraint(
            ["generation_job_id"], ["practice.generation_jobs.id"], ondelete="CASCADE"
        ),
        sa.PrimaryKeyConstraint("id"),
        sa.UniqueConstraint("idempotency_key"),
        schema="practice",
    )
    op.create_index(
        "ix_practice_outbox_claim",
        "outbox_events",
        ["processed_at", "lease_expires_at"],
        schema="practice",
    )
    op.execute(
        """
        DO $$
        BEGIN
          IF EXISTS (SELECT 1 FROM pg_roles WHERE rolname = 'course_tutor_practice') THEN
            GRANT USAGE ON SCHEMA practice TO course_tutor_practice;
            GRANT SELECT, INSERT, UPDATE, DELETE ON ALL TABLES IN SCHEMA practice
              TO course_tutor_practice;
            REVOKE ALL PRIVILEGES ON ALL TABLES IN SCHEMA public FROM course_tutor_practice;
          END IF;
        END $$
        """
    )


def downgrade() -> None:
    op.drop_index("ix_practice_outbox_claim", table_name="outbox_events", schema="practice")
    op.drop_table("outbox_events", schema="practice")
    op.drop_index("ix_practice_exercises_fingerprint", table_name="exercises", schema="practice")
    op.drop_table("exercises", schema="practice")
    op.drop_table("practice_sets", schema="practice")
    op.drop_index(
        "ix_generation_jobs_status_deadline", table_name="generation_jobs", schema="practice"
    )
    op.drop_index("ix_generation_jobs_owner", table_name="generation_jobs", schema="practice")
    op.drop_table("generation_jobs", schema="practice")
    op.drop_table("study_plan_modules", schema="practice")
    op.drop_index("ix_study_plans_tenant_book", table_name="study_plans", schema="practice")
    op.drop_table("study_plans", schema="practice")
    op.execute("DROP SCHEMA IF EXISTS practice")
