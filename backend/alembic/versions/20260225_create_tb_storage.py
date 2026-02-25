"""create tb_storage table

Revision ID: 20260225_storage
Revises: 20260225_sale_order_serials
Create Date: 2026-02-25

"""

from alembic import op
import sqlalchemy as sa

revision = "20260225_storage"
down_revision = "20260225_sale_order_serials"
branch_labels = None
depends_on = None


def upgrade() -> None:
    op.create_table(
        "tb_storage",
        sa.Column("comp_id", sa.Integer(), nullable=False),
        sa.Column("stor_id", sa.Integer(), nullable=False),
        sa.Column("stor_desc", sa.String(255), nullable=True),
        sa.Column("bra_id", sa.Integer(), nullable=True),
        sa.Column("stor_disabled", sa.Boolean(), nullable=True),
        sa.PrimaryKeyConstraint("comp_id", "stor_id"),
    )


def downgrade() -> None:
    op.drop_table("tb_storage")
