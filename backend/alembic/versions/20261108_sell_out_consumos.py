"""sell out: allocation rows, the recompute queue and the campaign VAT flag

Revision ID: 20261108_sell_out_consumos
Revises: 20261107_sell_in_bonos_marca
Create Date: 2026-11-08

Sell in / sell out, T7 slice S1. Inert: nothing writes these tables yet (the
allocator, its handler and the triggers that feed the queue come in later
slices).

- `sell_out_consumos`: what each sale takes from a campaign's cap, rebuilt
  from scratch per campaign by `app.services.sell_out.tope.asignar`. `monto`
  is in the campaign currency; `tc_venta` is the BNA rate of the sale day,
  frozen when the row is written (for `dia_venta` campaigns). `venta_ref` has
  NO foreign key, like `sell_in_consumos` (see `app.models.sell_out`).
- `sell_out_dirty`: one row per campaign waiting for a recompute.
- `sell_out_campanas.monto_incluye_iva`: whether the loaded amount includes
  VAT (owner, 2026-10-20); existing campaigns become `false`.
"""

from typing import Sequence, Union

import sqlalchemy as sa
from alembic import op

revision: str = "20261108_sell_out_consumos"
down_revision: Union[str, None] = "20261107_sell_in_bonos_marca"
branch_labels: Union[str, Sequence[str], None] = None
depends_on: Union[str, Sequence[str], None] = None


def upgrade() -> None:
    op.add_column(
        "sell_out_campanas",
        sa.Column("monto_incluye_iva", sa.Boolean(), nullable=False, server_default=sa.false()),
    )
    op.create_table(
        "sell_out_consumos",
        sa.Column("id", sa.BigInteger(), primary_key=True),
        sa.Column(
            "campana_id", sa.BigInteger(), sa.ForeignKey("sell_out_campanas.id", ondelete="CASCADE"), nullable=False
        ),
        sa.Column("canal", sa.String(8), nullable=False),
        sa.Column("venta_ref", sa.BigInteger(), nullable=False),  # no FK, like sell_in_consumos
        sa.Column("item_id", sa.Integer(), nullable=False),
        sa.Column("fecha_venta", sa.Date(), nullable=False),
        sa.Column("unidades", sa.Integer(), nullable=False),
        sa.Column("monto", sa.Numeric(18, 2), nullable=False),
        sa.Column("tc_venta", sa.Numeric(18, 6), nullable=True),
        sa.Column("created_at", sa.DateTime(timezone=True), nullable=False, server_default=sa.func.now()),
        sa.UniqueConstraint("campana_id", "canal", "venta_ref", name="uq_sell_out_consumos_campana_canal_venta"),
        sa.CheckConstraint("canal IN ('ml', 'fuera', 'tn')", name="ck_sell_out_consumos_canal"),
        sa.CheckConstraint("unidades > 0", name="ck_sell_out_consumos_unidades_positivas"),
        sa.CheckConstraint("monto >= 0", name="ck_sell_out_consumos_monto_no_negativo"),
        sa.CheckConstraint("tc_venta IS NULL OR tc_venta > 0", name="ck_sell_out_consumos_tc_venta_positivo"),
    )
    op.create_index("ix_sell_out_consumos_canal_venta", "sell_out_consumos", ["canal", "venta_ref"])
    op.create_table(
        "sell_out_dirty",
        sa.Column(
            "campana_id",
            sa.BigInteger(),
            sa.ForeignKey("sell_out_campanas.id", ondelete="CASCADE"),
            primary_key=True,
            autoincrement=False,
        ),
        sa.Column("enqueued_at", sa.DateTime(timezone=True), nullable=False, server_default=sa.func.now()),
        sa.Column("attempts", sa.Integer(), nullable=False, server_default="0"),
        sa.Column("last_error", sa.Text(), nullable=True),
    )


def downgrade() -> None:
    op.drop_table("sell_out_dirty")
    op.drop_index("ix_sell_out_consumos_canal_venta", table_name="sell_out_consumos")
    op.drop_table("sell_out_consumos")
    op.drop_column("sell_out_campanas", "monto_incluye_iva")
