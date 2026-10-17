"""The `sell_dirty` queue (sell-in-sell-out T4): which sale lines must have
their sell-in / sell-out allocation recomputed. No cron: writers queue a line
and `pg_notify('sell_dirty')`, and `sell.drain` (worker REGISTRY) drains it.

Three writers, all inside the transaction that changes the sale:

- `ventas_fuera_ml_metricas` (`canal = 'fuera'`) and
  `ventas_tienda_nube_metricas` (`canal = 'tn'`): row triggers, keyed by
  `it_transaction`. An INSERT or DELETE always queues; an UPDATE queues only
  when a column the allocation reads actually changes (`ALLOCATION_COLUMNS`),
  so the ERP sync rewriting a row with the same values queues nothing. An
  UPDATE that changes `it_transaction` queues both keys. The trigger does one
  upsert and one notify per row: no reads, no allocation work.
- `ml_sale_lines` (`canal = 'ml'`): `enqueue_ml`, called by
  `store_sale_lines` with the lines that appeared, changed or disappeared.

`UPGRADE_SQL`/`DOWNGRADE_SQL` are the live definition of the triggers; the
migration `20261031_sell_dirty_queue` carries a frozen copy and also owns the
table (`app.models.sell_dirty`).

A claimed row is locked (`FOR UPDATE SKIP LOCKED`): a trigger re-queueing the
same line waits for the drain's short transaction, then lands as a fresh row,
so a change made while the line was being processed is never lost.
"""

from __future__ import annotations

from typing import List, Sequence, Tuple

from sqlalchemy import text
from sqlalchemy.orm import Session

CHANNEL = "sell_dirty"
BATCH_SIZE = 500

# What the allocators read from a fuera / TN sale row. Changing anything else
# (customer, seller, commission...) does not move an allocation.
ALLOCATION_COLUMNS = ("it_transaction", "item_id", "cantidad", "fecha_venta", "signo", "monto_total", "costo_unitario")

UPGRADE_SQL: List[str] = [
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

DOWNGRADE_SQL: List[str] = [
    "DROP TRIGGER IF EXISTS trg_sell_dirty_tn_update ON ventas_tienda_nube_metricas",
    "DROP TRIGGER IF EXISTS trg_sell_dirty_tn_insert_delete ON ventas_tienda_nube_metricas",
    "DROP TRIGGER IF EXISTS trg_sell_dirty_fuera_update ON ventas_fuera_ml_metricas",
    "DROP TRIGGER IF EXISTS trg_sell_dirty_fuera_insert_delete ON ventas_fuera_ml_metricas",
    "DROP FUNCTION IF EXISTS sell_dirty_enqueue_venta()",
]

# A data-modifying CTE always runs, referenced or not. The notify is delivered
# at commit, and only if the transaction commits.
_ENQUEUE_ML_SQL = text(
    """
WITH queued AS (
    INSERT INTO sell_dirty (canal, venta_ref, item_id)
    SELECT 'ml', ref, item FROM unnest(CAST(:refs AS bigint[]), CAST(:items AS integer[])) AS t(ref, item)
    ON CONFLICT (canal, venta_ref) DO UPDATE
    SET item_id = EXCLUDED.item_id, enqueued_at = now(), attempts = 0, last_error = NULL
    RETURNING 1
)
SELECT pg_notify('sell_dirty', '')
"""
)

# Claim and ack in one statement: the INERT drain (T4) computes nothing, so
# there is nothing to settle between the claim and the delete. T5 splits it.
_ACK_SQL = text(
    """
DELETE FROM sell_dirty AS d
USING (
    SELECT canal, venta_ref FROM sell_dirty
    ORDER BY enqueued_at, canal, venta_ref
    LIMIT :limit
    FOR UPDATE SKIP LOCKED
) AS claimed
WHERE d.canal = claimed.canal AND d.venta_ref = claimed.venta_ref
RETURNING d.canal, d.venta_ref, d.item_id
"""
)


def enqueue_ml(db: Session, lines: Sequence[Tuple[int, int]]) -> None:
    """Queues `(item_row_id, product)` ML sale lines and notifies the drain.
    A line given twice keeps its LAST product. Keys are sorted, so two writers
    lock the queue rows in the same order. Does not commit; a no-op for no lines."""
    if not lines:
        return
    ordered = sorted(dict(lines).items())
    db.execute(_ENQUEUE_ML_SQL, {"refs": [ref for ref, _ in ordered], "items": [item for _, item in ordered]})


def ack_batch(db: Session, limit: int) -> List[Tuple[str, int, int]]:
    """Claims up to `limit` queued lines (skipping the ones another drain holds)
    and removes them. Returns `(canal, venta_ref, item_id)`. Does not commit."""
    return [tuple(row) for row in db.execute(_ACK_SQL, {"limit": limit})]
