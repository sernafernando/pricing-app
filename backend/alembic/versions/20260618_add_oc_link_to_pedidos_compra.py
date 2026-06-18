"""add oc link columns to pedidos_compra

Revision ID: 20260618_add_oc_link
Revises: 20260617_purchase_orders
Create Date: 2026-06-18

Adds 3 nullable logical-FK columns and a partial index to pedidos_compra
for linking a purchase order (OC) from the ERP mirror. Mirrors the
ct_transaction_id pattern (no physical FK against the read-only mirror).
"""

from alembic import op
import sqlalchemy as sa

# revision identifiers, used by Alembic.
revision = "20260618_add_oc_link"
down_revision = "20260617_purchase_orders"
branch_labels = None
depends_on = None


def upgrade() -> None:
    op.add_column("pedidos_compra", sa.Column("oc_comp_id", sa.Integer(), nullable=True))
    op.add_column("pedidos_compra", sa.Column("oc_bra_id", sa.Integer(), nullable=True))
    op.add_column("pedidos_compra", sa.Column("oc_poh_id", sa.BigInteger(), nullable=True))
    op.create_index(
        "ix_pedidos_compra_oc_poh",
        "pedidos_compra",
        ["oc_comp_id", "oc_bra_id", "oc_poh_id"],
        postgresql_where=sa.text("oc_poh_id IS NOT NULL"),
    )


def downgrade() -> None:
    op.drop_index("ix_pedidos_compra_oc_poh", table_name="pedidos_compra")
    op.drop_column("pedidos_compra", "oc_poh_id")
    op.drop_column("pedidos_compra", "oc_bra_id")
    op.drop_column("pedidos_compra", "oc_comp_id")
