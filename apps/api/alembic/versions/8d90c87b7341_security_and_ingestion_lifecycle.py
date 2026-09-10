"""security and ingestion lifecycle

Revision ID: 8d90c87b7341
Revises: c0ae084fe021
"""

from collections.abc import Sequence

import sqlalchemy as sa
from alembic import op
from sqlalchemy.dialects import postgresql

revision: str = "8d90c87b7341"
down_revision: str | None = "c0ae084fe021"
branch_labels: str | Sequence[str] | None = None
depends_on: str | Sequence[str] | None = None


def upgrade() -> None:
    op.create_table(
        "programmes",
        sa.Column("id", sa.UUID(), nullable=False),
        sa.Column("tenant_id", sa.UUID(), nullable=False),
        sa.Column("code", sa.String(64), nullable=False),
        sa.Column("name", sa.String(255), nullable=False),
        sa.Column("created_at", sa.DateTime(), server_default=sa.func.now(), nullable=False),
        sa.Column("updated_at", sa.DateTime(), server_default=sa.func.now(), nullable=False),
        sa.ForeignKeyConstraint(["tenant_id"], ["tenants.id"], ondelete="CASCADE"),
        sa.PrimaryKeyConstraint("id"),
        sa.UniqueConstraint("tenant_id", "code"),
    )
    op.execute(
        """
        INSERT INTO programmes (id, tenant_id, code, name, created_at, updated_at)
        SELECT gen_random_uuid(), tenants.id, 'legacy', 'Migrated programme', now(), now()
        FROM tenants
        WHERE EXISTS (SELECT 1 FROM courses WHERE courses.tenant_id = tenants.id)
        """
    )
    op.add_column("courses", sa.Column("programme_id", sa.UUID(), nullable=True))
    op.execute(
        """
        UPDATE courses
        SET programme_id = programmes.id
        FROM programmes
        WHERE programmes.tenant_id = courses.tenant_id AND programmes.code = 'legacy'
        """
    )
    op.alter_column("courses", "programme_id", nullable=False)
    op.create_foreign_key(
        "fk_courses_programme_id_programmes",
        "courses",
        "programmes",
        ["programme_id"],
        ["id"],
        ondelete="RESTRICT",
    )
    op.execute(
        """
        INSERT INTO source_roots (
            id, tenant_id, absolute_path, last_scanned_at, created_at, updated_at
        )
        SELECT gen_random_uuid(), tenant_id, '/unconfigured/' || id::text, NULL, now(), now()
        FROM courses
        WHERE source_root_id IS NULL
        """
    )
    op.execute(
        """
        UPDATE courses
        SET source_root_id = source_roots.id
        FROM source_roots
        WHERE courses.source_root_id IS NULL
          AND source_roots.absolute_path = '/unconfigured/' || courses.id::text
        """
    )
    op.create_table(
        "course_runs",
        sa.Column("id", sa.UUID(), nullable=False),
        sa.Column("course_id", sa.UUID(), nullable=False),
        sa.Column("run_key", sa.String(128), nullable=False),
        sa.Column("source_root_id", sa.UUID(), nullable=False),
        sa.Column("active_content_version_id", sa.UUID(), nullable=True),
        sa.Column("created_at", sa.DateTime(), server_default=sa.func.now(), nullable=False),
        sa.Column("updated_at", sa.DateTime(), server_default=sa.func.now(), nullable=False),
        sa.ForeignKeyConstraint(["course_id"], ["courses.id"], ondelete="CASCADE"),
        sa.ForeignKeyConstraint(["source_root_id"], ["source_roots.id"]),
        sa.PrimaryKeyConstraint("id"),
        sa.UniqueConstraint("course_id", "run_key"),
    )
    op.create_foreign_key(
        "fk_course_runs_active_content_version_id_content_versions",
        "course_runs",
        "content_versions",
        ["active_content_version_id"],
        ["id"],
    )
    op.execute(
        """
        INSERT INTO course_runs (
            id, course_id, run_key, source_root_id, active_content_version_id,
            created_at, updated_at
        )
        SELECT gen_random_uuid(), id, 'legacy', source_root_id, active_content_version_id,
               now(), now()
        FROM courses
        """
    )
    op.add_column("content_versions", sa.Column("course_run_id", sa.UUID(), nullable=True))
    op.execute(
        """
        UPDATE content_versions
        SET course_run_id = course_runs.id
        FROM course_runs
        WHERE course_runs.course_id = content_versions.course_id
          AND course_runs.run_key = 'legacy'
        """
    )
    op.alter_column("content_versions", "course_run_id", nullable=False)
    op.create_foreign_key(
        "fk_content_versions_course_run_id_course_runs",
        "content_versions",
        "course_runs",
        ["course_run_id"],
        ["id"],
        ondelete="CASCADE",
    )
    op.drop_constraint("uq_content_versions_course_id", "content_versions", type_="unique")
    op.create_unique_constraint(
        "uq_content_versions_course_run_id",
        "content_versions",
        ["course_run_id", "pipeline_version", "sequence"],
    )
    op.add_column("source_roots", sa.Column("last_snapshot_hash", sa.String(64), nullable=True))
    op.add_column(
        "source_roots",
        sa.Column("scan_interval_seconds", sa.Integer(), server_default="900", nullable=False),
    )
    op.alter_column("source_roots", "scan_interval_seconds", server_default=None)
    op.add_column(
        "content_versions", sa.Column("source_snapshot_hash", sa.String(64), nullable=True)
    )
    # Two files may legitimately have identical bytes. Path is the identity inside
    # one immutable version; checksum remains the change detector.
    op.drop_constraint("uq_source_documents_version_checksum", "source_documents", type_="unique")
    op.create_table(
        "audit_events",
        sa.Column("id", sa.UUID(), nullable=False),
        sa.Column("tenant_id", sa.UUID(), nullable=False),
        sa.Column("actor_user_id", sa.UUID(), nullable=False),
        sa.Column("action", sa.String(128), nullable=False),
        sa.Column("resource_type", sa.String(64), nullable=False),
        sa.Column("resource_id", sa.String(255), nullable=False),
        sa.Column(
            "details",
            postgresql.JSONB(astext_type=sa.Text()),
            nullable=False,
        ),
        sa.Column("created_at", sa.DateTime(), server_default=sa.func.now(), nullable=False),
        sa.Column("updated_at", sa.DateTime(), server_default=sa.func.now(), nullable=False),
        sa.ForeignKeyConstraint(["tenant_id"], ["tenants.id"], ondelete="CASCADE"),
        sa.PrimaryKeyConstraint("id"),
    )
    op.create_index("ix_audit_events_tenant_created", "audit_events", ["tenant_id", "created_at"])
    op.create_index("ix_audit_events_actor", "audit_events", ["actor_user_id"])


def downgrade() -> None:
    op.drop_index("ix_audit_events_actor", table_name="audit_events")
    op.drop_index("ix_audit_events_tenant_created", table_name="audit_events")
    op.drop_table("audit_events")
    op.create_unique_constraint(
        "uq_source_documents_version_checksum",
        "source_documents",
        ["version_id", "checksum"],
    )
    op.drop_column("content_versions", "source_snapshot_hash")
    op.drop_constraint("uq_content_versions_course_run_id", "content_versions", type_="unique")
    op.create_unique_constraint(
        "uq_content_versions_course_id",
        "content_versions",
        ["course_id", "pipeline_version", "sequence"],
    )
    op.drop_constraint(
        "fk_content_versions_course_run_id_course_runs",
        "content_versions",
        type_="foreignkey",
    )
    op.drop_column("content_versions", "course_run_id")
    op.drop_table("course_runs")
    op.drop_constraint("fk_courses_programme_id_programmes", "courses", type_="foreignkey")
    op.drop_column("courses", "programme_id")
    op.drop_table("programmes")
    op.drop_column("source_roots", "scan_interval_seconds")
    op.drop_column("source_roots", "last_snapshot_hash")
