"""create tb_rma_add_items table

Revision ID: 20260225_rma_add_items
Revises: 20260225_rma_header
Create Date: 2026-02-25

"""

from alembic import op
import sqlalchemy as sa

revision = "20260225_rma_add_items"
down_revision = "20260225_rma_header"
branch_labels = None
depends_on = None


def upgrade() -> None:
    op.create_table(
        "tb_rma_add_items",
        # PK
        sa.Column("comp_id", sa.Integer(), nullable=False),
        sa.Column("rmah_id", sa.BigInteger(), nullable=False),
        sa.Column("rmad_id", sa.BigInteger(), nullable=False),
        sa.Column("rmaai_id", sa.BigInteger(), nullable=False),
        # Data
        sa.Column("item_id", sa.BigInteger(), nullable=True),
        sa.Column("rmaai_qty", sa.Numeric(18, 6), nullable=True),
        sa.Column("rmaai_price", sa.Numeric(18, 4), nullable=True),
        sa.Column("curr_id", sa.Integer(), nullable=True),
        # PK constraint
        sa.PrimaryKeyConstraint("comp_id", "rmah_id", "rmad_id", "rmaai_id"),
    )
    # Indexes
    op.create_index("idx_rmaai_item_id", "tb_rma_add_items", ["item_id"])
    op.create_index("idx_rmaai_rmah_id", "tb_rma_add_items", ["rmah_id"])
    op.create_index("idx_rmaai_rmad_id", "tb_rma_add_items", ["rmad_id"])


def downgrade() -> None:
    op.drop_index("idx_rmaai_rmad_id", table_name="tb_rma_add_items")
    op.drop_index("idx_rmaai_rmah_id", table_name="tb_rma_add_items")
    op.drop_index("idx_rmaai_item_id", table_name="tb_rma_add_items")
    op.drop_table("tb_rma_add_items")
