"""create rrhh_hikvision_users cache table

Revision ID: 20260316a1
Revises: fa4b31d7998e
Create Date: 2026-03-16
"""

from alembic import op
import sqlalchemy as sa

revision = "20260316a1"
down_revision = "fa4b31d7998e"
branch_labels = None
depends_on = None


def upgrade() -> None:
    op.create_table(
        "rrhh_hikvision_users",
        sa.Column("id", sa.Integer(), primary_key=True, index=True),
        sa.Column("employee_no", sa.String(20), unique=True, nullable=False, index=True),
        sa.Column("name", sa.String(200), nullable=False, server_default=""),
        sa.Column("user_type", sa.String(50), nullable=True),
        sa.Column("valid_begin", sa.String(30), nullable=True),
        sa.Column("valid_end", sa.String(30), nullable=True),
        sa.Column("synced_at", sa.DateTime(timezone=True), server_default=sa.func.now()),
    )


def downgrade() -> None:
    op.drop_table("rrhh_hikvision_users")
