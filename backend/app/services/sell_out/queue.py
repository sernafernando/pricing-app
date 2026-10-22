"""The `sell_out_dirty` queue (sell-in-sell-out T7 S3): which sell-out campaigns
must have their `sell_out_consumos` rebuilt (`asignacion.recalcular`). No cron:
every writer queues campaign ids in its own transaction and
`pg_notify('sell_out_dirty')`; the `sell_out.drain` worker drains it.

Writers (all in the transaction of the change):
- `sell.drain`, for the sale lines it drains (`enqueue_ventas`): the campaigns
  holding consumptions of those lines (what they held before the change) plus
  the active campaigns whose reach covers the line's CURRENT product and whose
  range covers its CURRENT date (a return included: only a return inside the
  range moves the cap, `alcance`). A settled ML order arrives this way too.
- the campaigns API (`campanas`): a load, an edit (the campaign and the ones
  that shared products with it BEFORE the edit), a void and a payment rate.
- the BNA update (`tipo_cambio_service.guardar_cotizacion_bna`, in a savepoint,
  `enqueue_por_bna`).
- statement triggers (`triggers`, T7 S4) for what never passes through the app:
  offsets API group filters, `productos_erp` reach/VAT columns, and a sale's
  `cust_id` / `costo_total` change.

A queued campaign re-queued while the drain holds it (`FOR UPDATE SKIP LOCKED`
for the drain's short transaction) waits for that transaction, then lands as a
fresh row (`ON CONFLICT DO UPDATE`, attempts reset): a change made while the
campaign is being rebuilt is never lost. `DO NOTHING` would see the locked row
and skip, and the drain's ack would then drop that change.

Writers sort the ids, so two of them lock the queue rows in the same order.
Postgres only (`pg_notify`, `SKIP LOCKED`): on any other database a writer is a
no-op, like the worker itself.
"""

from __future__ import annotations

from collections import defaultdict
from contextlib import contextmanager
from datetime import date, datetime
from typing import Dict, Iterable, Iterator, List, Optional, Sequence, Set, Tuple

from sqlalchemy import func, or_, text, tuple_
from sqlalchemy.orm import Session

from app.models.ml_sale_line import MlSaleLine
from app.models.sell_out import SellOutCampana, SellOutConsumo
from app.services.sell_in.costing import VENTAS_FACTURADAS
from app.services.sell_out import alcance

CHANNEL = "sell_out_dirty"
BATCH_SIZE = 50
# A campaign is retried on later wakes until it fails this many times; a new change re-queues it with attempts = 0.
MAX_ATTEMPTS = 5
# How long a writer waits for a campaign's queue row held by a running `sell_out.drain` batch.
LOCK_TIMEOUT = "2s"

Line = Tuple[str, int]  # (canal, venta_ref)

# A data-modifying CTE always runs; the notify is delivered at commit, and only if it commits.
_ENQUEUE_SQL = text(
    """
WITH queued AS (
    INSERT INTO sell_out_dirty (campana_id)
    SELECT c.id FROM sell_out_campanas AS c WHERE c.id = ANY(CAST(:ids AS bigint[])) ORDER BY c.id
    ON CONFLICT (campana_id) DO UPDATE SET enqueued_at = now(), attempts = 0, last_error = NULL
    RETURNING 1
)
SELECT pg_notify('sell_out_dirty', '') WHERE EXISTS (SELECT 1 FROM queued)
"""
)

# The oldest queued campaigns, fresh ones first, skipping what another drain holds, parked ones and
# the ones that already failed in this run. Locked until the batch's transaction ends.
_CLAIM_SQL = text(
    """
SELECT campana_id FROM sell_out_dirty
WHERE attempts < :max_attempts AND campana_id <> ALL(CAST(:excluded AS bigint[]))
ORDER BY attempts, enqueued_at, campana_id
LIMIT :limit
FOR UPDATE SKIP LOCKED
"""
)

# One campaign with the version claimed (`enqueued_at`, moved by every re-queue): the one-by-one retry.
_CLAIM_ONE_SQL = text(
    "SELECT enqueued_at FROM sell_out_dirty WHERE campana_id = :id AND attempts < :max_attempts FOR UPDATE SKIP LOCKED"
)

_DONE_SQL = text("DELETE FROM sell_out_dirty WHERE campana_id = ANY(CAST(:ids AS bigint[]))")

# Charges a campaign only while it is still the version that failed: a re-queue that landed after
# the failed transaction rolled back is a fresh change.
_CHARGE_SQL = text(
    "UPDATE sell_out_dirty SET attempts = attempts + 1, last_error = :error "
    "WHERE campana_id = :id AND enqueued_at = :enqueued_at RETURNING attempts"
)


def _postgres(db: Session) -> bool:
    return db.get_bind().dialect.name == "postgresql"


@contextmanager
def lock_timeout(db: Session, timeout: str) -> Iterator[None]:
    """A savepoint whose statements wait at most `timeout` for a lock (then 55P03, lock_not_available);
    the session's previous `lock_timeout` is restored before it is released (`SET LOCAL` would otherwise
    last until the transaction ends). An error rolls back to the savepoint and propagates. Off Postgres
    (where the writers are no-ops) it only runs the block."""
    if not _postgres(db):
        yield
        return
    with db.begin_nested():
        previo = db.execute(text("SELECT current_setting('lock_timeout')")).scalar()
        db.execute(text("SELECT set_config('lock_timeout', :t, true)"), {"t": timeout})
        yield
        db.execute(text("SELECT set_config('lock_timeout', :t, true)"), {"t": previo})


def enqueue(db: Session, campana_ids: Iterable[int]) -> None:
    """Queues the given campaigns (ids that no longer exist are ignored) and notifies the drain.
    Does not commit; a no-op for no ids or off Postgres."""
    ids = sorted({int(i) for i in campana_ids})
    if ids and _postgres(db):
        db.execute(_ENQUEUE_SQL, {"ids": ids})


def campanas_de_ventas(db: Session, lines: Sequence[Line]) -> Set[int]:
    """The campaigns a change of these sale lines can move (module docstring). One query per
    channel present, one over the consumptions and one over the reach."""
    por_canal: Dict[str, List[int]] = defaultdict(list)
    for canal, ref in set(lines):
        por_canal[canal].append(ref)
    if not por_canal:
        return set()
    t = SellOutConsumo
    claves = [tuple_(t.canal, t.venta_ref).in_([(c, r) for c, refs in por_canal.items() for r in refs])]
    ids = {cid for (cid,) in db.query(t.campana_id).filter(*claves).distinct()}

    ventas: List[Tuple[int, date]] = []
    if por_canal.get("ml"):
        ventas += db.query(MlSaleLine.product, MlSaleLine.day).filter(MlSaleLine.item_row_id.in_(por_canal["ml"]))
    for canal, model in VENTAS_FACTURADAS:
        if por_canal.get(canal):
            dia = func.date(func.timezone("UTC", model.fecha_venta))  # the UTC date, like `alcance.ventas`
            ventas += db.query(model.item_id, dia).filter(model.it_transaction.in_(por_canal[canal]))
    return ids | alcance.campanas_por_venta(db, [(int(item), dia) for item, dia in ventas if item is not None])


def enqueue_ventas(db: Session, lines: Sequence[Line]) -> None:
    """Queues the campaigns a change of these sale lines can move. Does not commit."""
    if lines and _postgres(db):
        enqueue(db, campanas_de_ventas(db, lines))


def enqueue_por_bna(db: Session, fecha: date) -> None:
    """Queues the active USD campaigns a new BNA rate dated `fecha` can move: the `al_cobro` ones
    without their rate (they follow the latest BNA) and the `dia_venta` ones still running on or after
    `fecha` (a sale converts at the latest rate on or before its day). `fijo` and a defined `al_cobro`
    convert at their own rate. Does not commit."""
    if not _postgres(db):
        return
    c = SellOutCampana
    sin_tasa = (c.tc_modo == "al_cobro") & c.tipo_cambio.is_(None)
    dia_venta = (c.tc_modo == "dia_venta") & (c.fecha_hasta >= fecha)
    rows = db.query(c.id).filter(c.estado == "activa", c.moneda == "USD", or_(sin_tasa, dia_venta))
    enqueue(db, [cid for (cid,) in rows])


def claim_batch(db: Session, limit: int, excluded: Iterable[int] = ()) -> List[int]:
    """Claims up to `limit` queued campaigns, locked until the transaction ends. Does not commit."""
    params = {"max_attempts": MAX_ATTEMPTS, "excluded": sorted(set(excluded)), "limit": limit}
    return [int(row[0]) for row in db.execute(_CLAIM_SQL, params)]


def claim_one(db: Session, campana_id: int) -> Optional[datetime]:
    """Claims one queued campaign and returns the version claimed; None when it is gone, parked or held."""
    row = db.execute(_CLAIM_ONE_SQL, {"id": campana_id, "max_attempts": MAX_ATTEMPTS}).first()
    return row[0] if row is not None else None


def ack(db: Session, campana_ids: Iterable[int]) -> None:
    """Removes the rebuilt campaigns, in the transaction that claimed them. Does not commit."""
    ids = sorted(set(campana_ids))
    if ids:
        db.execute(_DONE_SQL, {"ids": ids})


def charge(db: Session, campana_id: int, error: str, enqueued_at: datetime) -> Optional[int]:
    """Charges one campaign if it is still the version claimed; returns its attempts, or None. Does not commit."""
    row = db.execute(_CHARGE_SQL, {"id": campana_id, "error": error, "enqueued_at": enqueued_at}).first()
    return row[0] if row is not None else None
