"""Fill sales flagged without a TP-Link cost when a list-8 price shows up
(metricas-ml-tplink-mode P2, the worker half; the script half is
`app/scripts/backfill_tp_cost.py`).

A sale whose `costo_tp_*` columns are NULL is flagged "Total TP incomplete".
When the ERP later loads a list-8 price for its item, these triggers queue the
item in `tp_cost_fill_queue` and `pg_notify` the worker:

- `tb_item_cost_list` (current list), coslis_id 8: on insert, and on an update
  that actually changes `coslis_price` or `curr_id` (a sync that rewrites the
  same values queues nothing);
- `tb_item_cost_list_history`, coslis_id 8: on insert. The resolver reads the
  HISTORY, and `sync_all_incremental` syncs the current list BEFORE the history:
  woken by the current list alone, the worker would run before the history row
  exists, dequeue the item and fill nothing.

The handler (`app/workers/handlers/tp_cost_fill.py`) drains the queue in
batches, one short transaction each: claim items, find the NULL rows of those
items and of the combos containing them, and resolve them with the backfill
script's own `_procesar_lote` -- same rules (price at the sale date, else the
first price flagged approximate, combo precedence, rejected prices stay NULL),
same `costo_tp_unitario_ars IS NULL` guard on the UPDATE so a TP cost already
set is never rewritten. An item that still does not resolve is dequeued anyway:
the next list-8 change queues it again.

The metrics recompute is not done here: setting `costo_tp_unitario_ars` fires
the `ml_order_item_costos` UPDATE trigger (20261027_tp_metrics_columns), which
queues it at low priority.

`UPGRADE_SQL`/`DOWNGRADE_SQL` are the live definition; the migration
`20261029_tp_cost_fill_queue` carries a frozen copy.
"""

from __future__ import annotations

from dataclasses import dataclass
from typing import List

from sqlalchemy import text
from sqlalchemy.orm import Session

from app.models.ml_order_item_costo import MlOrderItemCosto
from app.models.ml_orders_ops import MlOrdersOps
from app.models.tb_item_association import TbItemAssociation
from app.scripts.backfill_tp_cost import BackfillTpResult, _procesar_lote

CHANNEL = "tp_cost_fill"
BATCH_ITEMS = 50

UPGRADE_SQL: List[str] = [
    """
CREATE TABLE IF NOT EXISTS tp_cost_fill_queue (
    item_id INTEGER PRIMARY KEY,
    enqueued_at TIMESTAMPTZ NOT NULL DEFAULT now()
)
""",
    """
CREATE OR REPLACE FUNCTION tp_cost_fill_enqueue() RETURNS TRIGGER AS $trg$
BEGIN
    INSERT INTO tp_cost_fill_queue (item_id) VALUES (NEW.item_id)
    ON CONFLICT (item_id) DO UPDATE SET enqueued_at = now();
    PERFORM pg_notify('tp_cost_fill', '');
    RETURN NULL;
END;
$trg$ LANGUAGE plpgsql
""",
    """
CREATE TRIGGER trg_tp_cost_fill_list_insert
AFTER INSERT ON tb_item_cost_list
FOR EACH ROW WHEN (NEW.coslis_id = 8 AND NEW.item_id IS NOT NULL)
EXECUTE FUNCTION tp_cost_fill_enqueue()
""",
    """
CREATE TRIGGER trg_tp_cost_fill_list_update
AFTER UPDATE OF coslis_price, curr_id ON tb_item_cost_list
FOR EACH ROW WHEN (
    NEW.coslis_id = 8 AND NEW.item_id IS NOT NULL
    AND (OLD.coslis_price IS DISTINCT FROM NEW.coslis_price OR OLD.curr_id IS DISTINCT FROM NEW.curr_id)
)
EXECUTE FUNCTION tp_cost_fill_enqueue()
""",
    """
CREATE TRIGGER trg_tp_cost_fill_history_insert
AFTER INSERT ON tb_item_cost_list_history
FOR EACH ROW WHEN (NEW.coslis_id = 8 AND NEW.item_id IS NOT NULL)
EXECUTE FUNCTION tp_cost_fill_enqueue()
""",
]

DOWNGRADE_SQL: List[str] = [
    "DROP TRIGGER IF EXISTS trg_tp_cost_fill_history_insert ON tb_item_cost_list_history",
    "DROP TRIGGER IF EXISTS trg_tp_cost_fill_list_update ON tb_item_cost_list",
    "DROP TRIGGER IF EXISTS trg_tp_cost_fill_list_insert ON tb_item_cost_list",
    "DROP FUNCTION IF EXISTS tp_cost_fill_enqueue()",
    "DROP TABLE IF EXISTS tp_cost_fill_queue",
]

# The ONE query an empty queue costs: a pick in primary-key order (index) on
# a table that is empty almost all the time. Claimed rows are deleted in the same
# transaction that fills their sales, so a failure rolls the claim back.
_CLAIM_SQL = text(
    """
DELETE FROM tp_cost_fill_queue
WHERE item_id IN (
    SELECT item_id FROM tp_cost_fill_queue
    ORDER BY item_id
    LIMIT :limit
    FOR UPDATE SKIP LOCKED
)
RETURNING item_id
"""
)


@dataclass
class FillBatch:
    items: int
    result: BackfillTpResult


def fill_batch(db: Session, limit: int) -> FillBatch:
    """Claims up to `limit` queued items and fills the NULL TP cost of their
    sales and of the sales of combos containing them. Does not commit."""
    items = [row[0] for row in db.execute(_CLAIM_SQL, {"limit": limit})]
    result = BackfillTpResult()
    if not items:
        return FillBatch(items=0, result=result)

    combos = {
        row[0]
        for row in db.query(TbItemAssociation.item_id).filter(
            TbItemAssociation.item_id_1.in_(items), TbItemAssociation.iasso_qty > 0
        )
        if row[0] is not None
    }
    # `ix_ml_order_item_costos_tp_pendiente`: partial index on
    # `producto_item_id` WHERE `costo_tp_unitario_ars IS NULL`.
    rows = (
        db.query(MlOrderItemCosto.id, MlOrderItemCosto.producto_item_id, MlOrdersOps.date_created)
        .outerjoin(MlOrdersOps, MlOrdersOps.order_id == MlOrderItemCosto.order_id)
        .filter(
            MlOrderItemCosto.costo_tp_unitario_ars.is_(None),
            MlOrderItemCosto.producto_item_id.in_(sorted(set(items) | combos)),
        )
        .order_by(MlOrderItemCosto.id)
        .all()
    )
    if rows:
        _procesar_lote(db, rows, False, result)
        result.examined = len(rows)
    return FillBatch(items=len(items), result=result)
