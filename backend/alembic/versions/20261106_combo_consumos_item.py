"""combos: a sale's campaign and cost-bonus rows are unique per product too

Revision ID: 20261106_combo_consumos_item
Revises: 20261106_sell_in_modo_manual
Create Date: 2026-11-06

Owner (2026-11-05): "El combo consume los lotes de sell in de cada componente y cuenta para sus campañas de sell
out." A combo sale counts for each of its components under the sale's own `venta_ref`, so two components of one sale
may be reached by the same sell-out campaign or the same % of cost bonus. `sell_out_consumos` was unique on
`(campana_id, canal, venta_ref)` and `sell_in_bono_consumos` on `(bono_id, canal, venta_ref)`: both widen to include
`item_id`. No data changes: every existing row is already unique on the narrower key.

LOCK NOTE: dropping and adding a unique constraint takes an ACCESS EXCLUSIVE lock while the new index builds (both
tables hold one row per counted sale and campaign or bonus, thousands, not millions). Run with
`lock_timeout = '5s'` like `20261106_sell_in_modo_manual` (the sell-out and sell-in drains write these tables),
restoring the previous value; stop the pricing worker if it times out.

Downgrade: keeps, per sale and campaign or bonus, the row with the lowest id and deletes the other components' rows
(they would break the narrow key); their campaigns and bonuses are short of that sell out until they are rebuilt.
"""

from typing import Sequence, Union

from alembic import op

revision: str = "20261106_combo_consumos_item"
down_revision: Union[str, None] = "20261106_sell_in_modo_manual"
branch_labels: Union[str, Sequence[str], None] = None
depends_on: Union[str, Sequence[str], None] = None

# (table, owner column, narrow constraint, wide constraint)
_CLAVES = (
    (
        "sell_out_consumos",
        "campana_id",
        "uq_sell_out_consumos_campana_canal_venta",
        "uq_sell_out_consumos_campana_canal_venta_item",
    ),
    (
        "sell_in_bono_consumos",
        "bono_id",
        "uq_sell_in_bono_consumos_bono_canal_venta",
        "uq_sell_in_bono_consumos_bono_canal_venta_item",
    ),
)


def _con_lock_timeout(sentencias: Sequence[str]) -> None:
    previo = op.get_bind().exec_driver_sql("SHOW lock_timeout").scalar()
    op.execute("SET lock_timeout = '5s'")
    for sentencia in sentencias:
        op.execute(sentencia)
    op.execute(f"SET lock_timeout = '{previo}'")


def upgrade() -> None:
    sentencias = []
    for tabla, duenio, angosta, ancha in _CLAVES:
        sentencias += [
            f"ALTER TABLE {tabla} DROP CONSTRAINT {angosta}",
            f"ALTER TABLE {tabla} ADD CONSTRAINT {ancha} UNIQUE ({duenio}, canal, venta_ref, item_id)",
        ]
    _con_lock_timeout(sentencias)


def downgrade() -> None:
    sentencias = []
    for tabla, duenio, angosta, ancha in _CLAVES:
        sentencias += [
            f"DELETE FROM {tabla} t USING {tabla} o WHERE t.{duenio} = o.{duenio} AND t.canal = o.canal "
            f"AND t.venta_ref = o.venta_ref AND t.id > o.id",
            f"ALTER TABLE {tabla} DROP CONSTRAINT {ancha}",
            f"ALTER TABLE {tabla} ADD CONSTRAINT {angosta} UNIQUE ({duenio}, canal, venta_ref)",
        ]
    _con_lock_timeout(sentencias)
