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
items and of the combos containing them, and resolve them with
`tp_cost_resolver.procesar_lote`, shared with the backfill script -- same rules (price at the sale date, else the
first price flagged approximate, combo precedence, rejected prices stay NULL),
same `costo_tp_unitario_ars IS NULL` guard on the UPDATE so a TP cost already
set is never rewritten. An item that still does not resolve (no usable price)
leaves the queue anyway: the next list-8 change queues it again. An item whose
fill FAILS (an error) is isolated in its own savepoint, charged an attempt with
`last_error`, and parked after `MAX_ATTEMPTS`; a new list-8 change resets it.

The metrics recompute is not done here: setting `costo_tp_unitario_ars` fires
the `ml_order_item_costos` UPDATE trigger (20261027_tp_metrics_columns), which
queues it at low priority.

`UPGRADE_SQL`/`DOWNGRADE_SQL` are the live definition; the migration
`20261029_tp_cost_fill_queue` carries a frozen copy.
"""

from __future__ import annotations

import logging
from dataclasses import dataclass, field
from functools import partial
from typing import Any, Callable, Dict, Iterable, List, Optional, Sequence, Set

from sqlalchemy import text
from sqlalchemy.orm import Session

from app.models.ml_order_item_costo import MlOrderItemCosto
from app.models.ml_orders_ops import MlOrdersOps
from app.models.tb_item_association import TbItemAssociation
from app.services.ml_orders_ingestion.tp_cost_resolver import SKIP_ERROR, BackfillTpResult, procesar_lote

logger = logging.getLogger(__name__)

CHANNEL = "tp_cost_fill"
BATCH_ITEMS = 50
# Failed runs after which an item is PARKED: never claimed again until its
# list-8 price changes, which re-queues it with `attempts = 0`. Same shape as
# `order_metrics.queue`'s POISON_THRESHOLD.
MAX_ATTEMPTS = 5

UPGRADE_SQL: List[str] = [
    """
CREATE TABLE IF NOT EXISTS tp_cost_fill_queue (
    item_id INTEGER PRIMARY KEY,
    enqueued_at TIMESTAMPTZ NOT NULL DEFAULT now(),
    attempts INTEGER NOT NULL DEFAULT 0,
    last_error TEXT
)
""",
    """
CREATE OR REPLACE FUNCTION tp_cost_fill_enqueue() RETURNS TRIGGER AS $trg$
BEGIN
    INSERT INTO tp_cost_fill_queue (item_id) VALUES (NEW.item_id)
    ON CONFLICT (item_id) DO UPDATE SET enqueued_at = now(), attempts = 0, last_error = NULL;
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

# The ONE query an empty queue costs, on a table that is empty almost all the
# time. Parked items (`attempts >= MAX_ATTEMPTS`) are never claimed; items that
# already failed in THIS run are excluded so they cannot spin it. Fresh items
# (`attempts = 0`) go first. The rows stay in the queue, locked, until their
# own outcome is settled in the same transaction.
_CLAIM_SQL = text(
    """
SELECT item_id FROM tp_cost_fill_queue
WHERE attempts < :max_attempts AND NOT (item_id = ANY(CAST(:excluded AS integer[])))
ORDER BY attempts, item_id
LIMIT :limit
FOR UPDATE SKIP LOCKED
"""
)
_DONE_SQL = text("DELETE FROM tp_cost_fill_queue WHERE item_id = :item_id")
_FAILED_SQL = text(
    "UPDATE tp_cost_fill_queue SET attempts = attempts + 1, last_error = :error WHERE item_id = :item_id"
)


@dataclass
class FillBatch:
    items: int
    failed: List[int] = field(default_factory=list)
    combo_failed: List[int] = field(default_factory=list)
    result: BackfillTpResult = field(default_factory=BackfillTpResult)


def _combos_de(db: Session, items: Sequence[int]) -> Dict[int, Set[int]]:
    """`{component: {combos containing it}}` for the whole batch, one query."""
    combos: Dict[int, Set[int]] = {}
    for combo_id, componente_id in db.query(TbItemAssociation.item_id, TbItemAssociation.item_id_1).filter(
        TbItemAssociation.item_id_1.in_(items), TbItemAssociation.iasso_qty > 0
    ):
        if combo_id is not None:
            combos.setdefault(componente_id, set()).add(combo_id)
    return combos


def _sumar(total: BackfillTpResult, parcial: BackfillTpResult) -> None:
    total.examined += parcial.examined
    total.resolved += parcial.resolved
    total.written += parcial.written
    total.skipped.update(parcial.skipped)
    total.resolved_by_fuente.update(parcial.resolved_by_fuente)
    total.written_by_fuente.update(parcial.written_by_fuente)


def _llenar(
    db: Session, filas: Sequence[Any], total: BackfillTpResult, after: Optional[Callable[[], Any]] = None
) -> None:
    """Fills `filas` inside their OWN savepoint, then runs `after` in it. Any
    failure, including a row the resolver could not handle, rolls the
    savepoint back and re-raises; on success the counts join `total`."""
    parcial = BackfillTpResult(examined=len(filas))
    savepoint = db.begin_nested()
    try:
        if filas:
            # Rows already filled earlier in this batch are a no-op: the
            # UPDATE's `IS NULL` guard.
            procesar_lote(db, filas, False, parcial)
        if parcial.skipped[SKIP_ERROR]:
            raise RuntimeError(f"{parcial.skipped[SKIP_ERROR]} row(s) failed to resolve")
        if after is not None:
            after()
        savepoint.commit()
    except Exception:
        savepoint.rollback()
        raise
    _sumar(total, parcial)


def fill_batch(db: Session, limit: int, excluded: Iterable[int] = ()) -> FillBatch:
    """Claims up to `limit` queued items and fills the NULL TP cost of their
    sales and of the sales of combos containing them. Does not commit.

    Each item's OWN sales run in their own savepoint: a failure (an
    exception, or a row the resolver could not handle) rolls back that item's
    writes only, charges it an attempt with the error, and leaves the rest of
    the batch going. An item that succeeds leaves the queue.

    Each combo containing a claimed item runs in ANOTHER savepoint, once per
    batch: a broken combo never charges, undoes or parks its component. It is
    logged and reported in `combo_failed`, its sales stay NULL (flagged), and
    it is retried the next time any of its components is queued -- the combo
    has no queue row of its own to charge or park.

    An error outside any savepoint (claim, lookups) propagates: the caller's
    transaction rolls back and the queue is unchanged.
    """
    batch = FillBatch(items=0)
    items = [
        row[0]
        for row in db.execute(
            _CLAIM_SQL, {"max_attempts": MAX_ATTEMPTS, "excluded": sorted(set(excluded)), "limit": limit}
        )
    ]
    if not items:
        return batch
    batch.items = len(items)

    combos = _combos_de(db, items)
    productos = set(items).union(*combos.values())
    # `ix_ml_order_item_costos_tp_pendiente`: partial index on
    # `producto_item_id` WHERE `costo_tp_unitario_ars IS NULL`.
    rows = (
        db.query(MlOrderItemCosto.id, MlOrderItemCosto.producto_item_id, MlOrdersOps.date_created)
        .outerjoin(MlOrdersOps, MlOrdersOps.order_id == MlOrderItemCosto.order_id)
        .filter(
            MlOrderItemCosto.costo_tp_unitario_ars.is_(None),
            MlOrderItemCosto.producto_item_id.in_(sorted(productos)),
        )
        .order_by(MlOrderItemCosto.id)
        .all()
    )

    # Grouped once (rows arrive ordered by id, and keep that order per product).
    filas_por_producto: Dict[int, List[Any]] = {}
    for row in rows:
        filas_por_producto.setdefault(row.producto_item_id, []).append(row)

    # Each cost row is resolved at most ONCE per batch: a queued item can also
    # be a combo of another queued item, which would reach its rows twice.
    # Rows are taken when attempted, whatever the outcome -- a failed item's
    # rows are retried with that item, not through another one.
    vistas: Set[int] = set()

    def _filas(producto_item_id: int) -> List[Any]:
        nuevas = [row for row in filas_por_producto.get(producto_item_id, []) if row.id not in vistas]
        vistas.update(row.id for row in nuevas)
        return nuevas

    combos_hechos: Set[int] = set()
    for item_id in items:
        try:
            _llenar(db, _filas(item_id), batch.result, after=partial(db.execute, _DONE_SQL, {"item_id": item_id}))
        except Exception as exc:  # noqa: BLE001 -- one item must never stop the batch
            logger.warning("tp_cost.fill: item_id=%s failed: %s", item_id, exc, exc_info=True)
            db.execute(_FAILED_SQL, {"item_id": item_id, "error": str(exc)[:500]})
            batch.failed.append(item_id)

        for combo_id in sorted(combos.get(item_id, set()) - combos_hechos):
            combos_hechos.add(combo_id)
            filas = _filas(combo_id)
            if not filas:
                continue
            try:
                _llenar(db, filas, batch.result)
            except Exception as exc:  # noqa: BLE001 -- a combo must never charge its component
                logger.warning(
                    "tp_cost.fill: combo item_id=%s (via component %s) failed: %s",
                    combo_id,
                    item_id,
                    exc,
                    exc_info=True,
                )
                batch.combo_failed.append(combo_id)
    return batch
