"""Add functional index on UPPER(is_serial) for case-insensitive search

Revision ID: 20260312_upper_serial_idx
Revises: 20260311_estado_manual_perm
Create Date: 2026-03-12
"""

from alembic import op

revision = "20260312_upper_serial_idx"
down_revision = "20260311_estado_manual_perm"
branch_labels = None
depends_on = None


def upgrade() -> None:
    op.execute("CREATE INDEX IF NOT EXISTS idx_item_serials_upper_serial ON tb_item_serials (UPPER(is_serial))")
    op.execute("CREATE INDEX IF NOT EXISTS idx_rma_detail_upper_serial ON tb_rma_detail (UPPER(rmad_serial))")


def downgrade() -> None:
    op.execute("DROP INDEX IF EXISTS idx_item_serials_upper_serial")
    op.execute("DROP INDEX IF EXISTS idx_rma_detail_upper_serial")
