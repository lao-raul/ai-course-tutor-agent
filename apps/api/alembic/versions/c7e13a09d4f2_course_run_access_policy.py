"""server-owned course-run access policy

Revision ID: c7e13a09d4f2
Revises: b6a4d2c8e901
"""

from collections.abc import Sequence

import sqlalchemy as sa
from alembic import op
from sqlalchemy.dialects import postgresql

revision: str = "c7e13a09d4f2"
down_revision: str | None = "b6a4d2c8e901"
branch_labels: str | Sequence[str] | None = None
depends_on: str | Sequence[str] | None = None

COURSE_ACCESS_POLICY = postgresql.ENUM(
    "explicit_membership",
    "tenant_authenticated",
    name="course_access_policy",
    create_type=False,
)


def upgrade() -> None:
    bind = op.get_bind()
    COURSE_ACCESS_POLICY.create(bind, checkfirst=True)
    op.add_column(
        "course_runs",
        sa.Column(
            "access_policy",
            COURSE_ACCESS_POLICY,
            server_default="explicit_membership",
            nullable=False,
        ),
    )
    op.alter_column("course_runs", "access_policy", server_default=None)


def downgrade() -> None:
    op.drop_column("course_runs", "access_policy")
    COURSE_ACCESS_POLICY.drop(op.get_bind(), checkfirst=True)
