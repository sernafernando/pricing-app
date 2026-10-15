"""sell in: purchases, their items and consumptions

Revision ID: 20261024_sell_in_tables
Revises: 20261023_ml_billing_flex_drop_recompute_trigger
Create Date: 2026-10-24

New tables only (sell in / sell out, T1). Legacy offsets are untouched.
`sell_in_consumos.venta_ref` has no FK on purpose: `ml_sale_lines` is deleted
and reinserted on every store.
"""

from typing import Sequence, Union

import sqlalchemy as sa
from alembic import op

revision: str = "20261024_sell_in_tables"
down_revision: Union[str, None] = "20261023_ml_billing_flex_drop_recompute_trigger"
branch_labels: Union[str, Sequence[str], None] = None
depends_on: Union[str, Sequence[str], None] = None


def upgrade() -> None:
    op.create_table(
        "sell_in_compras",
        sa.Column("id", sa.BigInteger(), primary_key=True),
        sa.Column("proveedor_id", sa.Integer(), sa.ForeignKey("proveedores.id", ondelete="RESTRICT"), nullable=True),
        sa.Column(
            "pedido_compra_id", sa.BigInteger(), sa.ForeignKey("pedidos_compra.id", ondelete="SET NULL"), nullable=True
        ),
        sa.Column("fecha_compra", sa.Date(), nullable=False),
        sa.Column("fecha_ingreso", sa.Date(), nullable=True),
        sa.Column("cuenta_desde", sa.String(16), nullable=False, server_default="compra"),
        sa.Column("moneda", sa.String(3), nullable=False),
        sa.Column("monto_total", sa.Numeric(18, 2), nullable=False),
        sa.Column("tipo_cambio", sa.Numeric(18, 6), nullable=True),
        sa.Column("formula", sa.String(16), nullable=False, server_default="proporcional"),
        sa.Column("estado", sa.String(16), nullable=False, server_default="activa"),
        sa.Column("descripcion", sa.Text(), nullable=True),
        sa.Column("usuario_id", sa.Integer(), sa.ForeignKey("usuarios.id", ondelete="RESTRICT"), nullable=False),
        sa.Column("created_at", sa.DateTime(timezone=True), nullable=False, server_default=sa.func.now()),
        sa.Column("updated_at", sa.DateTime(timezone=True), nullable=False, server_default=sa.func.now()),
        sa.CheckConstraint("cuenta_desde IN ('compra', 'ingreso')", name="ck_sell_in_compras_cuenta_desde"),
        sa.CheckConstraint(
            "cuenta_desde <> 'ingreso' OR fecha_ingreso IS NOT NULL", name="ck_sell_in_compras_ingreso_con_fecha"
        ),
        sa.CheckConstraint("moneda IN ('ARS', 'USD')", name="ck_sell_in_compras_moneda"),
        sa.CheckConstraint("monto_total > 0", name="ck_sell_in_compras_monto_positivo"),
        sa.CheckConstraint("moneda <> 'USD' OR tipo_cambio IS NOT NULL", name="ck_sell_in_compras_usd_con_tc"),
        sa.CheckConstraint("formula IN ('proporcional', 'por_unidad', 'manual')", name="ck_sell_in_compras_formula"),
        sa.CheckConstraint("estado IN ('activa', 'anulada')", name="ck_sell_in_compras_estado"),
    )
    op.create_index("ix_sell_in_compras_proveedor_id", "sell_in_compras", ["proveedor_id"])

    op.create_table(
        "sell_in_compra_items",
        sa.Column("id", sa.BigInteger(), primary_key=True),
        sa.Column(
            "compra_id", sa.BigInteger(), sa.ForeignKey("sell_in_compras.id", ondelete="CASCADE"), nullable=False
        ),
        sa.Column("item_id", sa.Integer(), sa.ForeignKey("productos_erp.item_id"), nullable=False),
        sa.Column("cantidad", sa.Integer(), nullable=False),
        sa.Column("costo_base_unit", sa.Numeric(18, 6), nullable=False),
        sa.Column("monto_asignado", sa.Numeric(18, 2), nullable=False),
        sa.UniqueConstraint("compra_id", "item_id", name="uq_sell_in_compra_items_compra_item"),
        sa.CheckConstraint("cantidad > 0", name="ck_sell_in_compra_items_cantidad_positiva"),
        sa.CheckConstraint("monto_asignado >= 0", name="ck_sell_in_compra_items_monto_no_negativo"),
    )
    op.create_index("ix_sell_in_compra_items_item_id", "sell_in_compra_items", ["item_id"])

    op.create_table(
        "sell_in_consumos",
        sa.Column("id", sa.BigInteger(), primary_key=True),
        sa.Column(
            "compra_item_id",
            sa.BigInteger(),
            sa.ForeignKey("sell_in_compra_items.id", ondelete="CASCADE"),
            nullable=False,
        ),
        sa.Column("canal", sa.String(8), nullable=False),
        sa.Column("venta_ref", sa.BigInteger(), nullable=False),
        sa.Column("item_id", sa.Integer(), nullable=False),
        sa.Column("fecha_venta", sa.Date(), nullable=False),
        sa.Column("unidades", sa.Integer(), nullable=False),
        sa.Column("descuento_ars", sa.Numeric(18, 2), nullable=False),
        sa.UniqueConstraint("canal", "venta_ref", "compra_item_id", name="uq_sell_in_consumos_canal_venta_item"),
        sa.CheckConstraint("canal IN ('ml', 'fuera', 'tn')", name="ck_sell_in_consumos_canal"),
        sa.CheckConstraint("unidades > 0", name="ck_sell_in_consumos_unidades_positivas"),
    )
    op.create_index("ix_sell_in_consumos_item_fecha", "sell_in_consumos", ["item_id", "fecha_venta"])


def downgrade() -> None:
    op.drop_table("sell_in_consumos")
    op.drop_table("sell_in_compra_items")
    op.drop_table("sell_in_compras")
