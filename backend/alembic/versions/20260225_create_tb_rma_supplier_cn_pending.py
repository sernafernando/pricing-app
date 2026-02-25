"""create tb_rma_supplier_cn_pending table

Revision ID: 20260225_rma_supplier_cn_pending
Revises: 20260225_rma_attrib_hist
Create Date: 2026-02-25

"""

from alembic import op
import sqlalchemy as sa

revision = "20260225_rma_supplier_cn_pending"
down_revision = "20260225_rma_attrib_hist"
branch_labels = None
depends_on = None


def upgrade() -> None:
    op.create_table(
        "tb_rma_supplier_cn_pending",
        # PK
        sa.Column("comp_id", sa.Integer(), nullable=False),
        sa.Column("rmanc_id", sa.BigInteger(), nullable=False),
        # Foreign keys
        sa.Column("rmah_id", sa.BigInteger(), nullable=True),
        sa.Column("rmad_id", sa.BigInteger(), nullable=True),
        sa.Column("supp_id", sa.BigInteger(), nullable=True),
        sa.Column("item_id", sa.BigInteger(), nullable=True),
        sa.Column("ct_transaction", sa.BigInteger(), nullable=True),
        sa.Column("curr_id", sa.Integer(), nullable=True),
        sa.Column("stor_id", sa.Integer(), nullable=True),
        # Data
        sa.Column("rmanc_price", sa.Numeric(18, 6), nullable=True),
        sa.Column("rmanc_qty", sa.Numeric(18, 4), nullable=True),
        sa.Column("rmanc_isProcessed", sa.Boolean(), nullable=True),
        # PK constraint
        sa.PrimaryKeyConstraint("comp_id", "rmanc_id"),
    )
    # Indexes
    op.create_index("idx_rmanc_rmah_id", "tb_rma_supplier_cn_pending", ["rmah_id"])
    op.create_index("idx_rmanc_rmad_id", "tb_rma_supplier_cn_pending", ["rmad_id"])
    op.create_index("idx_rmanc_supp_id", "tb_rma_supplier_cn_pending", ["supp_id"])
    op.create_index("idx_rmanc_item_id", "tb_rma_supplier_cn_pending", ["item_id"])


def downgrade() -> None:
    op.drop_index("idx_rmanc_item_id", table_name="tb_rma_supplier_cn_pending")
    op.drop_index("idx_rmanc_supp_id", table_name="tb_rma_supplier_cn_pending")
    op.drop_index("idx_rmanc_rmad_id", table_name="tb_rma_supplier_cn_pending")
    op.drop_index("idx_rmanc_rmah_id", table_name="tb_rma_supplier_cn_pending")
    op.drop_table("tb_rma_supplier_cn_pending")
