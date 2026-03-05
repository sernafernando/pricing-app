"""Add listo_envio_proveedor and shipping_id to rma_caso_items

Links RMA items to etiquetas_envio via shipping_id (string FK).
Adds listo_envio_proveedor boolean to mark items as ready for
supplier shipment (distinct from enviado_proveedor which means shipped).

Revision ID: 20260305_rma_item_ship
Revises: 20260305_rma_estado_caso
Create Date: 2026-03-05

"""

import sqlalchemy as sa
from alembic import op

revision = "20260305_rma_item_ship"
down_revision = "20260305_rma_estado_caso"
branch_labels = None
depends_on = None


def upgrade() -> None:
    op.add_column(
        "rma_caso_items",
        sa.Column("listo_envio_proveedor", sa.Boolean(), nullable=True),
    )
    op.add_column(
        "rma_caso_items",
        sa.Column("shipping_id", sa.String(50), nullable=True),
    )
    op.create_foreign_key(
        "fk_rma_item_shipping_id",
        "rma_caso_items",
        "etiquetas_envio",
        ["shipping_id"],
        ["shipping_id"],
    )
    op.create_index("ix_rma_caso_items_shipping_id", "rma_caso_items", ["shipping_id"])


def downgrade() -> None:
    op.drop_constraint("fk_rma_item_shipping_id", "rma_caso_items", type_="foreignkey")
    op.drop_index("ix_rma_caso_items_shipping_id", table_name="rma_caso_items")
    op.drop_column("rma_caso_items", "shipping_id")
    op.drop_column("rma_caso_items", "listo_envio_proveedor")
