"""Agregar índice en tb_sale_order_header.mlshippingid

El subquery de estado ERP en etiquetas flex hace JOIN
contra mlshippingid sin índice → sequential scan sobre toda
la tabla del ERP. Con índice pasa a ser index scan.

Revision ID: 20260219_idx_soh_mlship
Revises: 20260219_costo_override
Create Date: 2026-02-19

"""

from alembic import op

revision = "20260219_idx_soh_mlship"
down_revision = "20260219_costo_override"
branch_labels = None
depends_on = None


def upgrade():
    op.create_index(
        "ix_tb_sale_order_header_mlshippingid",
        "tb_sale_order_header",
        ["mlshippingid"],
    )


def downgrade():
    op.drop_index("ix_tb_sale_order_header_mlshippingid", table_name="tb_sale_order_header")
