"""ml_order_metrics / ml_sale_lines: TP-Link figures, and recompute on a TP cost

Revision ID: 20261027_tp_metrics_columns
Revises: 20261026_tplink_tema_permiso
Create Date: 2026-10-16

metricas-ml-tplink-mode / P3. The figures Métricas ML and Ventas ML will read
in TP mode, computed by the metrics drain next to the Gauss ones from the TP
cost P1 froze on `ml_order_item_costos`:

- `ml_order_metrics`: `costo_tp`, `total_tp` (= total_gauss +
  costo_mercaderia - costo_tp), `markup_tp` and `tp_incompleto`;
- `ml_sale_lines`: `tg_tp`, `mtg_tp`, `mcosto_tp`, split like `tg`/`mtg`/
  `mcosto`.

Every column is NULLABLE ON PURPOSE: NULL is "Total TP incomplete" (an item
without a TP cost), never 0. Existing rows stay NULL until their order is
recomputed; `tp_incompleto` NULL means "not computed yet".

The `ml_order_item_costos` UPDATE trigger now also fires when
`costo_tp_unitario_ars` changes: the TP backfill and the late-load worker set
it with an UPDATE, and the order must be recomputed through the same dirty
queue. Frozen copies of the new and the previous trigger are inlined below
(the module `order_metrics/triggers.py` is the live definition).

LOCK NOTE: ADD COLUMN of nullable columns with no default is metadata-only.
Replacing the trigger takes a brief SHARE ROW EXCLUSIVE lock on
`ml_order_item_costos`.
"""

from typing import Sequence, Union

import sqlalchemy as sa
from alembic import op

revision: str = "20261027_tp_metrics_columns"
down_revision: Union[str, None] = "20261026_tplink_tema_permiso"
branch_labels: Union[str, Sequence[str], None] = None
depends_on: Union[str, Sequence[str], None] = None

_METRICS_COLUMNS = (
    sa.Column("costo_tp", sa.Numeric(14, 2), nullable=True, comment="TP-Link cost of goods. NULL = incomplete."),
    sa.Column("total_tp", sa.Numeric(14, 2), nullable=True, comment="total_gauss + costo_mercaderia - costo_tp."),
    sa.Column("markup_tp", sa.Numeric(9, 2), nullable=True, comment="total_tp / costo_tp, as a percentage."),
    sa.Column(
        "tp_incompleto",
        sa.Boolean(),
        nullable=True,
        comment="True when an item lacks a TP cost. NULL = not computed yet.",
    ),
)

_LINES_COLUMNS = (
    sa.Column("tg_tp", sa.Numeric(), nullable=True),
    sa.Column("mtg_tp", sa.Numeric(), nullable=True),
    sa.Column("mcosto_tp", sa.Numeric(), nullable=True),
)

_DROP_UPDATE_TRIGGER = "DROP TRIGGER IF EXISTS trg_order_metrics_item_costos_update ON ml_order_item_costos"

_UPDATE_TRIGGER_SQL = """
CREATE TRIGGER trg_order_metrics_item_costos_update
AFTER UPDATE OF costo_unitario_ars, iva_pct, precio_unitario, costo_tp_unitario_ars ON ml_order_item_costos
FOR EACH ROW WHEN (
    OLD.costo_unitario_ars IS DISTINCT FROM NEW.costo_unitario_ars
    OR OLD.iva_pct IS DISTINCT FROM NEW.iva_pct
    OR OLD.precio_unitario IS DISTINCT FROM NEW.precio_unitario
    OR OLD.costo_tp_unitario_ars IS DISTINCT FROM NEW.costo_tp_unitario_ars
)
EXECUTE FUNCTION order_metrics_enqueue_order_item_costos();
"""

# As created by 20260923_ml_order_metrics_triggers_orders.
_PREVIOUS_UPDATE_TRIGGER_SQL = """
CREATE TRIGGER trg_order_metrics_item_costos_update
AFTER UPDATE OF costo_unitario_ars, iva_pct, precio_unitario ON ml_order_item_costos
FOR EACH ROW WHEN (
    OLD.costo_unitario_ars IS DISTINCT FROM NEW.costo_unitario_ars
    OR OLD.iva_pct IS DISTINCT FROM NEW.iva_pct
    OR OLD.precio_unitario IS DISTINCT FROM NEW.precio_unitario
)
EXECUTE FUNCTION order_metrics_enqueue_order_item_costos();
"""


def _is_postgres() -> bool:
    return op.get_bind().dialect.name == "postgresql"


def _fresh(column: sa.Column) -> sa.Column:
    """A new Column: one Column object cannot be attached to a table twice."""
    return sa.Column(column.name, column.type, nullable=column.nullable, comment=column.comment)


def upgrade() -> None:
    for column in _METRICS_COLUMNS:
        op.add_column("ml_order_metrics", _fresh(column))
    for column in _LINES_COLUMNS:
        op.add_column("ml_sale_lines", _fresh(column))
    if _is_postgres():
        op.execute(_DROP_UPDATE_TRIGGER)
        op.execute(_UPDATE_TRIGGER_SQL)


def downgrade() -> None:
    if _is_postgres():
        op.execute(_DROP_UPDATE_TRIGGER)
        op.execute(_PREVIOUS_UPDATE_TRIGGER_SQL)
    for column in reversed(_LINES_COLUMNS):
        op.drop_column("ml_sale_lines", column.name)
    for column in reversed(_METRICS_COLUMNS):
        op.drop_column("ml_order_metrics", column.name)
