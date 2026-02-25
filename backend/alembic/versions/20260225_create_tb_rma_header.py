"""create tb_rma_header table

Revision ID: 20260225_rma_header
Revises: 20260225_rma_detail
Create Date: 2026-02-25

"""

from alembic import op
import sqlalchemy as sa

revision = "20260225_rma_header"
down_revision = "20260225_rma_detail"
branch_labels = None
depends_on = None


def upgrade() -> None:
    op.create_table(
        "tb_rma_header",
        # PK
        sa.Column("comp_id", sa.Integer(), nullable=False),
        sa.Column("rmah_id", sa.BigInteger(), nullable=False),
        sa.Column("bra_id", sa.Integer(), nullable=False),
        # Foreign keys
        sa.Column("cust_id", sa.BigInteger(), nullable=True),
        sa.Column("supp_id", sa.BigInteger(), nullable=True),
        sa.Column("rmap_id", sa.Integer(), nullable=True),
        sa.Column("user_id_assigned", sa.BigInteger(), nullable=True),
        # Dates
        sa.Column("rmah_cd", sa.DateTime(), nullable=True),
        sa.Column("rmah_isEditingCD", sa.DateTime(), nullable=True),
        # Flags
        sa.Column("rmah_isEditing", sa.Boolean(), nullable=True),
        sa.Column("rmah_isInSuppplier", sa.Boolean(), nullable=True),
        # Notes
        sa.Column("rmah_note1", sa.String(4000), nullable=True),
        sa.Column("rmah_note2", sa.String(4000), nullable=True),
        # PK constraint
        sa.PrimaryKeyConstraint("comp_id", "rmah_id", "bra_id"),
    )
    # Indexes
    op.create_index("idx_rmah_cust_id", "tb_rma_header", ["cust_id"])
    op.create_index("idx_rmah_supp_id", "tb_rma_header", ["supp_id"])
    op.create_index("idx_rmah_cd", "tb_rma_header", ["rmah_cd"])
    op.create_index("idx_rmah_user_assigned", "tb_rma_header", ["user_id_assigned"])


def downgrade() -> None:
    op.drop_index("idx_rmah_user_assigned", table_name="tb_rma_header")
    op.drop_index("idx_rmah_cd", table_name="tb_rma_header")
    op.drop_index("idx_rmah_supp_id", table_name="tb_rma_header")
    op.drop_index("idx_rmah_cust_id", table_name="tb_rma_header")
    op.drop_table("tb_rma_header")
