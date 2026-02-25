"""create tb_sale_order_serials table

Revision ID: 20260225_sale_order_serials
Revises: 20260224_crear_envio
Create Date: 2026-02-25

"""

from alembic import op
import sqlalchemy as sa

revision = "20260225_sale_order_serials"
down_revision = "20260225_notif_markup"
branch_labels = None
depends_on = None


def upgrade() -> None:
    op.create_table(
        "tb_sale_order_serials",
        sa.Column("comp_id", sa.Integer(), nullable=False),
        sa.Column("bra_id", sa.Integer(), nullable=False),
        sa.Column("sose_id", sa.BigInteger(), nullable=False),
        sa.Column("is_id", sa.BigInteger(), nullable=True),
        sa.Column("soh_id", sa.BigInteger(), nullable=True),
        sa.Column("sose_guid", sa.String(100), nullable=True),
        sa.PrimaryKeyConstraint("comp_id", "bra_id", "sose_id"),
    )
    op.create_index("idx_sose_is_id", "tb_sale_order_serials", ["is_id"])
    op.create_index("idx_sose_soh_id", "tb_sale_order_serials", ["soh_id"])


def downgrade() -> None:
    op.drop_index("idx_sose_soh_id", table_name="tb_sale_order_serials")
    op.drop_index("idx_sose_is_id", table_name="tb_sale_order_serials")
    op.drop_table("tb_sale_order_serials")
