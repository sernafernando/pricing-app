"""create tb_rma_detail_attrib_history table

Revision ID: 20260225_rma_attrib_hist
Revises: 20260225_rma_add_items
Create Date: 2026-02-25

"""

from alembic import op
import sqlalchemy as sa

revision = "20260225_rma_attrib_hist"
down_revision = "20260225_rma_add_items"
branch_labels = None
depends_on = None


def upgrade() -> None:
    op.create_table(
        "tb_rma_detail_attrib_history",
        # PK
        sa.Column("comp_id", sa.Integer(), nullable=False),
        sa.Column("rmadh_id", sa.BigInteger(), nullable=False),
        # Foreign keys
        sa.Column("rmah_id", sa.BigInteger(), nullable=True),
        sa.Column("rmad_id", sa.BigInteger(), nullable=True),
        sa.Column("user_id", sa.BigInteger(), nullable=True),
        sa.Column("srpt_id", sa.Integer(), nullable=True),
        sa.Column("rmas_id", sa.Integer(), nullable=True),
        sa.Column("rmap_id", sa.Integer(), nullable=True),
        sa.Column("rmaw_id", sa.Integer(), nullable=True),
        sa.Column("rmamt_id", sa.Integer(), nullable=True),
        # Date
        sa.Column("rmadh_cd", sa.DateTime(), nullable=True),
        # PK constraint
        sa.PrimaryKeyConstraint("comp_id", "rmadh_id"),
    )
    # Indexes
    op.create_index("idx_rmadh_rmah_id", "tb_rma_detail_attrib_history", ["rmah_id"])
    op.create_index("idx_rmadh_rmad_id", "tb_rma_detail_attrib_history", ["rmad_id"])
    op.create_index("idx_rmadh_cd", "tb_rma_detail_attrib_history", ["rmadh_cd"])


def downgrade() -> None:
    op.drop_index("idx_rmadh_cd", table_name="tb_rma_detail_attrib_history")
    op.drop_index("idx_rmadh_rmad_id", table_name="tb_rma_detail_attrib_history")
    op.drop_index("idx_rmadh_rmah_id", table_name="tb_rma_detail_attrib_history")
    op.drop_table("tb_rma_detail_attrib_history")
