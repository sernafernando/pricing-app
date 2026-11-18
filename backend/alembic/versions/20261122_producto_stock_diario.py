"""producto_stock_diario: the daily stock photo (Auditoría de stock, Rotación)

Revision ID: 20261122_producto_stock_diario
Revises: 20261121_ml_publicaciones_auditoria_stock_perm
Create Date: 2026-11-18

One row per product per day with its ERP units (`productos_erp.stock`) and its Full units (its publications' user
products, each counted once), written by the `stock.snapshot` job of the existing worker and kept 400 days. The
Auditoría de stock averages the last 30 days for "Rotación (veces)". Only products with some stock get a row: a product
missing from a photographed day had none. A new table, nothing existing changes; downgrade drops it with its photos.
"""

from typing import Sequence, Union

import sqlalchemy as sa
from alembic import op

revision: str = "20261122_producto_stock_diario"
down_revision: Union[str, None] = "20261121_ml_publicaciones_auditoria_stock_perm"
branch_labels: Union[str, Sequence[str], None] = None
depends_on: Union[str, Sequence[str], None] = None


def upgrade() -> None:
    op.create_table(
        "producto_stock_diario",
        sa.Column("fecha", sa.Date(), nullable=False),
        sa.Column("item_id", sa.Integer(), nullable=False),
        sa.Column("stock_erp", sa.Integer(), nullable=False, server_default="0"),
        sa.Column("stock_full", sa.Integer(), nullable=False, server_default="0"),
        # fecha first: the window reads, the photographed days and the pruning all go by date
        sa.PrimaryKeyConstraint("fecha", "item_id", name="pk_producto_stock_diario"),
    )
    op.create_index("ix_producto_stock_diario_item_fecha", "producto_stock_diario", ["item_id", "fecha"])


def downgrade() -> None:
    op.drop_index("ix_producto_stock_diario_item_fecha", table_name="producto_stock_diario")
    op.drop_table("producto_stock_diario")
