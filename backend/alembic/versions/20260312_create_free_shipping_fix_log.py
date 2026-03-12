"""Create free_shipping_fix_log table for auto-fix tracking

Revision ID: 20260312_fs_fix_log
Revises: 20260312_upper_serial_idx
Create Date: 2026-03-12
"""

from alembic import op
import sqlalchemy as sa

revision = "20260312_fs_fix_log"
down_revision = "20260312_upper_serial_idx"
branch_labels = None
depends_on = None


def upgrade() -> None:
    op.create_table(
        "free_shipping_fix_log",
        sa.Column("id", sa.Integer(), primary_key=True, autoincrement=True),
        sa.Column("mla_id", sa.String(30), nullable=False, index=True),
        sa.Column("success", sa.Boolean(), nullable=False),
        sa.Column("skipped", sa.Boolean(), nullable=False, server_default="false"),
        sa.Column("skip_reason", sa.String(100), nullable=True),
        sa.Column("item_price", sa.String(30), nullable=True),
        sa.Column("mandatory_free_shipping", sa.Boolean(), nullable=False, server_default="false"),
        sa.Column("ml_response_status", sa.Integer(), nullable=True),
        sa.Column("ml_response_body", sa.Text(), nullable=True),
        sa.Column("created_at", sa.DateTime(timezone=True), server_default=sa.func.now(), nullable=False),
    )
    op.create_index(
        "idx_fs_fix_log_mla_created",
        "free_shipping_fix_log",
        ["mla_id", "created_at"],
    )


def downgrade() -> None:
    op.drop_index("idx_fs_fix_log_mla_created", table_name="free_shipping_fix_log")
    op.drop_table("free_shipping_fix_log")
