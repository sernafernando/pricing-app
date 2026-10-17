"""sell_dirty queue + fuera/TN triggers that wake sell.drain

Revision ID: 20261031_sell_dirty_queue
Revises: 20261030_ml_write_log
Create Date: 2026-10-17

sell-in-sell-out T4. `sell_dirty` holds the sale lines whose sell-in /
sell-out allocation must be recomputed (`app/models/sell_dirty.py`). Row
triggers on `ventas_fuera_ml_metricas` (canal 'fuera') and
`ventas_tienda_nube_metricas` (canal 'tn') queue the line by `it_transaction`
with its product and `pg_notify('sell_dirty')`: on INSERT and DELETE, and on
an UPDATE that actually changes a column the allocation reads. ML lines are
queued by `store_sale_lines` (no trigger). The `sell.drain` handler drains it
(inert until T5).

The trigger SQL is a frozen copy of `app/services/sell/queue.py`'s
`UPGRADE_SQL`/`DOWNGRADE_SQL` (that module is the live definition). The
downgrade drops everything this created.

LOCK NOTE: CREATE TRIGGER takes a SHARE ROW EXCLUSIVE lock on the two sale
tables for an instant; their ERP sync scripts retry on their next run.
"""

from typing import Sequence, Union

import sqlalchemy as sa
from alembic import op

revision: str = "20261031_sell_dirty_queue"
down_revision: Union[str, None] = "20261030_ml_write_log"
branch_labels: Union[str, Sequence[str], None] = None
depends_on: Union[str, Sequence[str], None] = None

_TRIGGERS_UP = [
    """
CREATE OR REPLACE FUNCTION sell_dirty_enqueue_venta() RETURNS TRIGGER AS $trg$
BEGIN
    IF TG_OP = 'DELETE' OR (TG_OP = 'UPDATE' AND OLD.it_transaction IS DISTINCT FROM NEW.it_transaction) THEN
        INSERT INTO sell_dirty (canal, venta_ref, item_id) VALUES (TG_ARGV[0], OLD.it_transaction, OLD.item_id)
        ON CONFLICT (canal, venta_ref) DO UPDATE
        SET item_id = EXCLUDED.item_id, enqueued_at = now(), attempts = 0, last_error = NULL;
    END IF;
    IF TG_OP <> 'DELETE' THEN
        INSERT INTO sell_dirty (canal, venta_ref, item_id) VALUES (TG_ARGV[0], NEW.it_transaction, NEW.item_id)
        ON CONFLICT (canal, venta_ref) DO UPDATE
        SET item_id = EXCLUDED.item_id, enqueued_at = now(), attempts = 0, last_error = NULL;
    END IF;
    PERFORM pg_notify('sell_dirty', '');
    RETURN NULL;
END;
$trg$ LANGUAGE plpgsql
""",
    """
CREATE TRIGGER trg_sell_dirty_fuera_insert_delete
AFTER INSERT OR DELETE ON ventas_fuera_ml_metricas
FOR EACH ROW EXECUTE FUNCTION sell_dirty_enqueue_venta('fuera')
""",
    """
CREATE TRIGGER trg_sell_dirty_fuera_update
AFTER UPDATE OF it_transaction, item_id, cantidad, fecha_venta, signo, monto_total, costo_unitario
ON ventas_fuera_ml_metricas
FOR EACH ROW WHEN (
    (OLD.it_transaction, OLD.item_id, OLD.cantidad, OLD.fecha_venta, OLD.signo, OLD.monto_total, OLD.costo_unitario)
    IS DISTINCT FROM
    (NEW.it_transaction, NEW.item_id, NEW.cantidad, NEW.fecha_venta, NEW.signo, NEW.monto_total, NEW.costo_unitario)
)
EXECUTE FUNCTION sell_dirty_enqueue_venta('fuera')
""",
    """
CREATE TRIGGER trg_sell_dirty_tn_insert_delete
AFTER INSERT OR DELETE ON ventas_tienda_nube_metricas
FOR EACH ROW EXECUTE FUNCTION sell_dirty_enqueue_venta('tn')
""",
    """
CREATE TRIGGER trg_sell_dirty_tn_update
AFTER UPDATE OF it_transaction, item_id, cantidad, fecha_venta, signo, monto_total, costo_unitario
ON ventas_tienda_nube_metricas
FOR EACH ROW WHEN (
    (OLD.it_transaction, OLD.item_id, OLD.cantidad, OLD.fecha_venta, OLD.signo, OLD.monto_total, OLD.costo_unitario)
    IS DISTINCT FROM
    (NEW.it_transaction, NEW.item_id, NEW.cantidad, NEW.fecha_venta, NEW.signo, NEW.monto_total, NEW.costo_unitario)
)
EXECUTE FUNCTION sell_dirty_enqueue_venta('tn')
""",
]

_TRIGGERS_DOWN = [
    "DROP TRIGGER IF EXISTS trg_sell_dirty_tn_update ON ventas_tienda_nube_metricas",
    "DROP TRIGGER IF EXISTS trg_sell_dirty_tn_insert_delete ON ventas_tienda_nube_metricas",
    "DROP TRIGGER IF EXISTS trg_sell_dirty_fuera_update ON ventas_fuera_ml_metricas",
    "DROP TRIGGER IF EXISTS trg_sell_dirty_fuera_insert_delete ON ventas_fuera_ml_metricas",
    "DROP FUNCTION IF EXISTS sell_dirty_enqueue_venta()",
]


def _is_postgres() -> bool:
    # plpgsql triggers and pg_notify: Postgres only (SQLite test schemas skip them).
    return op.get_bind().dialect.name == "postgresql"


def upgrade() -> None:
    op.create_table(
        "sell_dirty",
        sa.Column("canal", sa.String(length=8), nullable=False),
        sa.Column("venta_ref", sa.BigInteger(), autoincrement=False, nullable=False),
        sa.Column("item_id", sa.Integer(), nullable=True),
        sa.Column("enqueued_at", sa.DateTime(timezone=True), server_default=sa.text("now()"), nullable=False),
        sa.Column("attempts", sa.Integer(), server_default=sa.text("0"), nullable=False),
        sa.Column("last_error", sa.Text(), nullable=True),
        sa.CheckConstraint("canal IN ('ml', 'fuera', 'tn')", name="ck_sell_dirty_canal"),
        sa.PrimaryKeyConstraint("canal", "venta_ref"),
    )
    if _is_postgres():
        for statement in _TRIGGERS_UP:
            op.execute(statement)


def downgrade() -> None:
    if _is_postgres():
        for statement in _TRIGGERS_DOWN:
            op.execute(statement)
    op.drop_table("sell_dirty")
