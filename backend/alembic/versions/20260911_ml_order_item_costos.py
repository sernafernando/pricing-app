"""ml-ventas-modo-logistico PR3: ml_order_item_costos frozen cost snapshot

Revision ID: 20260911_costo_congelado
Revises: 20260911_modo_logistico
Create Date: 2026-09-11

New table only (design D4) — metadata-only, no backfill. Written exclusively
by `costeo_service.congelar()`, INSERT-only via `ON CONFLICT DO NOTHING`
(design D5): a re-ingestion of an order/item that already has a frozen row
never touches it, so a later ERP cost/IVA change can never retroactively
change an already-costed sale.
"""

from typing import Sequence, Union

import sqlalchemy as sa
from alembic import op

revision: str = "20260911_costo_congelado"
down_revision: Union[str, None] = "20260911_modo_logistico"
branch_labels: Union[str, Sequence[str], None] = None
depends_on: Union[str, Sequence[str], None] = None


def upgrade() -> None:
    op.create_table(
        "ml_order_item_costos",
        sa.Column("id", sa.Integer(), primary_key=True),
        sa.Column("order_id", sa.BigInteger(), nullable=False),
        sa.Column("item_id", sa.String(length=20), nullable=False),
        sa.Column("variation_id", sa.BigInteger(), nullable=True),
        sa.Column("costo_origen", sa.Numeric(14, 4), nullable=False),
        sa.Column("moneda", sa.String(length=3), nullable=False),
        sa.Column("tipo_cambio", sa.Numeric(14, 4), nullable=True),
        sa.Column("tipo_cambio_fecha", sa.Date(), nullable=True),
        sa.Column("costo_unitario_ars", sa.Numeric(14, 4), nullable=False),
        sa.Column("iva_pct", sa.Numeric(5, 2), nullable=False),
        sa.Column("precio_unitario", sa.Numeric(14, 2), nullable=False),
        sa.Column("fuente", sa.String(length=20), nullable=False),
        sa.Column("producto_item_id", sa.Integer(), nullable=False),
        sa.Column("congelado_at", sa.DateTime(timezone=True), nullable=False, server_default=sa.func.now()),
        sa.UniqueConstraint(
            "order_id",
            "item_id",
            "variation_id",
            name="uq_ml_order_item_costos_order_item_variation",
            postgresql_nulls_not_distinct=True,
        ),
    )
    op.create_index("ix_ml_order_item_costos_order_id", "ml_order_item_costos", ["order_id"])
    op.create_index("ix_ml_order_item_costos_item_id", "ml_order_item_costos", ["item_id"])


def downgrade() -> None:
    op.drop_index("ix_ml_order_item_costos_item_id", table_name="ml_order_item_costos")
    op.drop_index("ix_ml_order_item_costos_order_id", table_name="ml_order_item_costos")
    op.drop_table("ml_order_item_costos")
