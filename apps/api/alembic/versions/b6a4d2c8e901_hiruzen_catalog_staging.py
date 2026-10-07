"""Hiruzen Agent-owned catalog and ChinaTextbook staging

Revision ID: b6a4d2c8e901
Revises: f31b8d02c913
"""

from collections.abc import Sequence

import sqlalchemy as sa
from alembic import op
from sqlalchemy.dialects import postgresql

revision: str = "b6a4d2c8e901"
down_revision: str | None = "f31b8d02c913"
branch_labels: str | Sequence[str] | None = None
depends_on: str | Sequence[str] | None = None

CATEGORY_TYPE = postgresql.ENUM(
    "education_level",
    "subject",
    "publisher",
    "grade",
    name="category_type",
    create_type=False,
)
BOOK_STATUS = postgresql.ENUM(
    "draft", "published", "archived", name="book_lifecycle_status", create_type=False
)
IMPORT_STATUS = postgresql.ENUM(
    "running", "staged", "failed", name="catalog_import_status", create_type=False
)
CANDIDATE_STATUS = postgresql.ENUM(
    "staged",
    "needs_review",
    "approved",
    "imported",
    "rejected",
    name="catalog_candidate_status",
    create_type=False,
)


def upgrade() -> None:
    bind = op.get_bind()
    CATEGORY_TYPE.create(bind, checkfirst=True)
    BOOK_STATUS.create(bind, checkfirst=True)
    IMPORT_STATUS.create(bind, checkfirst=True)
    CANDIDATE_STATUS.create(bind, checkfirst=True)

    op.create_table(
        "categories",
        sa.Column("id", sa.UUID(), nullable=False),
        sa.Column("tenant_id", sa.UUID(), nullable=False),
        sa.Column("stable_key", sa.String(length=255), nullable=False),
        sa.Column("display_name", sa.String(length=255), nullable=False),
        sa.Column("category_type", CATEGORY_TYPE, nullable=False),
        sa.Column("parent_id", sa.UUID(), nullable=True),
        sa.Column("created_at", sa.DateTime(), server_default=sa.func.now(), nullable=False),
        sa.Column("updated_at", sa.DateTime(), server_default=sa.func.now(), nullable=False),
        sa.ForeignKeyConstraint(["parent_id"], ["categories.id"], ondelete="CASCADE"),
        sa.ForeignKeyConstraint(["tenant_id"], ["tenants.id"], ondelete="CASCADE"),
        sa.PrimaryKeyConstraint("id"),
        sa.UniqueConstraint("tenant_id", "stable_key", name="uq_categories_tenant_stable_key"),
    )
    op.create_index("ix_categories_tenant_type", "categories", ["tenant_id", "category_type"])

    op.create_table(
        "publishers",
        sa.Column("id", sa.UUID(), nullable=False),
        sa.Column("tenant_id", sa.UUID(), nullable=False),
        sa.Column("stable_key", sa.String(length=255), nullable=False),
        sa.Column("display_name", sa.String(length=255), nullable=False),
        sa.Column("normalized_name", sa.String(length=255), nullable=False),
        sa.Column("aliases", postgresql.JSONB(astext_type=sa.Text()), nullable=False),
        sa.Column("created_at", sa.DateTime(), server_default=sa.func.now(), nullable=False),
        sa.Column("updated_at", sa.DateTime(), server_default=sa.func.now(), nullable=False),
        sa.ForeignKeyConstraint(["tenant_id"], ["tenants.id"], ondelete="CASCADE"),
        sa.PrimaryKeyConstraint("id"),
        sa.UniqueConstraint(
            "tenant_id", "normalized_name", name="uq_publishers_tenant_normalized_name"
        ),
        sa.UniqueConstraint("tenant_id", "stable_key", name="uq_publishers_tenant_stable_key"),
    )

    education_level = postgresql.ENUM(name="education_level", create_type=False)
    op.create_table(
        "books",
        sa.Column("id", sa.UUID(), nullable=False),
        sa.Column("tenant_id", sa.UUID(), nullable=False),
        sa.Column("stable_key", sa.String(length=255), nullable=False),
        sa.Column("title", sa.String(length=500), nullable=False),
        sa.Column("normalized_title", sa.String(length=500), nullable=False),
        sa.Column("education_level", education_level, nullable=False),
        sa.Column("subject", sa.String(length=128), nullable=False),
        sa.Column("grade", sa.String(length=64), nullable=False),
        sa.Column("publisher_id", sa.UUID(), nullable=False),
        sa.Column("series", sa.String(length=255), nullable=False),
        sa.Column("edition", sa.String(length=255), nullable=True),
        sa.Column("start_grade", sa.String(length=64), nullable=True),
        sa.Column("editor", sa.String(length=128), nullable=True),
        sa.Column("term", sa.String(length=64), nullable=False),
        sa.Column("language", sa.String(length=16), nullable=False),
        sa.Column("isbn", sa.String(length=32), nullable=True),
        sa.Column("cover_uri", sa.Text(), nullable=True),
        sa.Column("lifecycle_status", BOOK_STATUS, nullable=False),
        sa.Column("created_at", sa.DateTime(), server_default=sa.func.now(), nullable=False),
        sa.Column("updated_at", sa.DateTime(), server_default=sa.func.now(), nullable=False),
        sa.ForeignKeyConstraint(["publisher_id"], ["publishers.id"], ondelete="RESTRICT"),
        sa.ForeignKeyConstraint(["tenant_id"], ["tenants.id"], ondelete="CASCADE"),
        sa.PrimaryKeyConstraint("id"),
        sa.UniqueConstraint("tenant_id", "stable_key", name="uq_books_tenant_stable_key"),
    )
    op.create_index("ix_books_education_level", "books", ["education_level"])
    op.create_index(
        "ix_books_catalog_filters",
        "books",
        ["tenant_id", "lifecycle_status", "education_level", "subject", "grade"],
    )

    op.create_table(
        "book_course_bindings",
        sa.Column("book_id", sa.UUID(), nullable=False),
        sa.Column("course_run_id", sa.UUID(), nullable=False),
        sa.ForeignKeyConstraint(["book_id"], ["books.id"], ondelete="CASCADE"),
        sa.ForeignKeyConstraint(["course_run_id"], ["course_runs.id"], ondelete="CASCADE"),
        sa.PrimaryKeyConstraint("book_id", "course_run_id"),
    )
    op.create_table(
        "book_content_bindings",
        sa.Column("id", sa.UUID(), nullable=False),
        sa.Column("book_id", sa.UUID(), nullable=False),
        sa.Column("course_run_id", sa.UUID(), nullable=False),
        sa.Column("source_root_id", sa.UUID(), nullable=False),
        sa.Column("source_id", sa.UUID(), nullable=False),
        sa.Column("content_version_id", sa.UUID(), nullable=False),
        sa.Column("created_at", sa.DateTime(), server_default=sa.func.now(), nullable=False),
        sa.Column("updated_at", sa.DateTime(), server_default=sa.func.now(), nullable=False),
        sa.ForeignKeyConstraint(["book_id"], ["books.id"], ondelete="CASCADE"),
        sa.ForeignKeyConstraint(
            ["content_version_id"], ["content_versions.id"], ondelete="RESTRICT"
        ),
        sa.ForeignKeyConstraint(["course_run_id"], ["course_runs.id"], ondelete="CASCADE"),
        sa.ForeignKeyConstraint(["source_id"], ["source_documents.id"], ondelete="RESTRICT"),
        sa.ForeignKeyConstraint(["source_root_id"], ["source_roots.id"], ondelete="RESTRICT"),
        sa.PrimaryKeyConstraint("id"),
        sa.UniqueConstraint(
            "book_id",
            "content_version_id",
            "source_id",
            name="uq_book_content_version_source",
        ),
    )

    op.create_table(
        "catalog_import_batches",
        sa.Column("id", sa.UUID(), nullable=False),
        sa.Column("tenant_id", sa.UUID(), nullable=False),
        sa.Column("source_root_id", sa.UUID(), nullable=False),
        sa.Column("selection", postgresql.JSONB(astext_type=sa.Text()), nullable=False),
        sa.Column("snapshot_hash", sa.String(length=64), nullable=False),
        sa.Column("status", IMPORT_STATUS, nullable=False),
        sa.Column("candidate_count", sa.Integer(), nullable=False),
        sa.Column("needs_review_count", sa.Integer(), nullable=False),
        sa.Column("failure_reason", sa.Text(), nullable=True),
        sa.Column("completed_at", sa.DateTime(), nullable=True),
        sa.Column("created_at", sa.DateTime(), server_default=sa.func.now(), nullable=False),
        sa.Column("updated_at", sa.DateTime(), server_default=sa.func.now(), nullable=False),
        sa.ForeignKeyConstraint(["source_root_id"], ["source_roots.id"], ondelete="RESTRICT"),
        sa.ForeignKeyConstraint(["tenant_id"], ["tenants.id"], ondelete="CASCADE"),
        sa.PrimaryKeyConstraint("id"),
        sa.UniqueConstraint(
            "source_root_id", "snapshot_hash", name="uq_catalog_batch_root_snapshot"
        ),
    )
    op.create_index(
        "ix_catalog_import_batches_tenant_created",
        "catalog_import_batches",
        ["tenant_id", "created_at"],
    )

    op.create_table(
        "catalog_import_candidates",
        sa.Column("id", sa.UUID(), nullable=False),
        sa.Column("batch_id", sa.UUID(), nullable=False),
        sa.Column("stable_key", sa.String(length=255), nullable=False),
        sa.Column("relative_path", sa.Text(), nullable=False),
        sa.Column("checksum", sa.String(length=64), nullable=False),
        sa.Column("size_bytes", sa.Integer(), nullable=False),
        sa.Column("metadata", postgresql.JSONB(astext_type=sa.Text()), nullable=False),
        sa.Column("status", CANDIDATE_STATUS, nullable=False),
        sa.Column("issues", postgresql.JSONB(astext_type=sa.Text()), nullable=False),
        sa.Column("imported_book_id", sa.UUID(), nullable=True),
        sa.Column("created_at", sa.DateTime(), server_default=sa.func.now(), nullable=False),
        sa.Column("updated_at", sa.DateTime(), server_default=sa.func.now(), nullable=False),
        sa.ForeignKeyConstraint(["batch_id"], ["catalog_import_batches.id"], ondelete="CASCADE"),
        sa.ForeignKeyConstraint(["imported_book_id"], ["books.id"], ondelete="SET NULL"),
        sa.PrimaryKeyConstraint("id"),
        sa.UniqueConstraint("batch_id", "relative_path", name="uq_catalog_candidate_batch_path"),
    )
    op.create_index(
        "ix_catalog_candidates_batch_status",
        "catalog_import_candidates",
        ["batch_id", "status"],
    )


def downgrade() -> None:
    op.drop_index("ix_catalog_candidates_batch_status", table_name="catalog_import_candidates")
    op.drop_table("catalog_import_candidates")
    op.drop_index("ix_catalog_import_batches_tenant_created", table_name="catalog_import_batches")
    op.drop_table("catalog_import_batches")
    op.drop_table("book_content_bindings")
    op.drop_table("book_course_bindings")
    op.drop_index("ix_books_catalog_filters", table_name="books")
    op.drop_index("ix_books_education_level", table_name="books")
    op.drop_table("books")
    op.drop_table("publishers")
    op.drop_index("ix_categories_tenant_type", table_name="categories")
    op.drop_table("categories")

    bind = op.get_bind()
    CANDIDATE_STATUS.drop(bind, checkfirst=True)
    IMPORT_STATUS.drop(bind, checkfirst=True)
    BOOK_STATUS.drop(bind, checkfirst=True)
    CATEGORY_TYPE.drop(bind, checkfirst=True)
