"""Recompute an item's promo price columns right after ml-webhook updates its promo mirror
(promo-ml-precio-inmediato T1).

Before this, a promo started from ML (seller center or ML's automatic offers) reached the pricing
columns only through the `sync_promo_prices` cron, 3 times a day. Now ml-webhook calls
`POST /api/promociones/recompute-precios` with the MLAs whose mirror rows it just wrote:

1. `enqueue_mlas` maps the MLAs to items (`PublicacionML`) and upserts one row per item in
   `promo_price_recompute_queue`. Repeated notifications for the same item collapse into that
   row; a new request also un-parks it (`attempts = 0`).
2. The `promo_price.recompute` handler (own thread in the ML worker, every few seconds, no cron)
   calls `drain`: per item it first reads the activation time from the mirror, with no pricing
   transaction open (the latest `updated_at` of the item's candidate/started rows, the same value
   the cron uses), then runs the SAME `recompute_item` as the panel apply and the cron in its own
   short `get_background_db()` session. So last-write-wins vs a manual price, MIN across started
   promos and frozen-on-end are unchanged. An item with no active mirror row has no started promo
   to write: it leaves the queue without a recompute (never `recompute_item(now=None)`, which
   would mean "activated now").
3. The row is deleted in the same transaction as the write, unless a new request rewrote its
   `enqueued_at` meanwhile (then it stays for the next pass). A recompute failure is charged to
   the row (`attempts`, `last_error`) and the item is parked at `MAX_ATTEMPTS` until a new
   request; the cron watermark still catches it. A mirror that cannot be read is NOT charged to
   the items: the pass stops (`mirror_unavailable`) and the queue waits untouched, so an outage
   never parks the whole queue.

Kill switch: with `PROMOS_WRITE_ENABLED` off the drain reads and writes nothing and the queue is
kept, like the cron.
"""

from __future__ import annotations

import logging
from dataclasses import dataclass, field
from datetime import UTC, datetime
from typing import Dict, Iterable, List, Set, Tuple

from sqlalchemy import bindparam, text
from sqlalchemy.dialects.postgresql import insert as pg_insert
from sqlalchemy.dialects.sqlite import insert as sqlite_insert
from sqlalchemy.orm import Session

from app.core.config import settings
from app.core.database import get_background_db, get_mlwebhook_engine
from app.models.promo_price_recompute_queue import PromoPriceRecomputeQueue
from app.models.publicacion_ml import PublicacionML
from app.services.promo_price_propagation import recompute_item

logger = logging.getLogger(__name__)

MAX_MLAS_PER_REQUEST = 50
BATCH_ITEMS = 50
# Failed runs after which an item is parked: not claimed again until a new request resets it.
MAX_ATTEMPTS = 5
_ERROR_MAX_CHARS = 500


@dataclass
class EnqueueResult:
    items_queued: int
    unknown_mlas: List[str]


@dataclass
class DrainResult:
    recomputed: int = 0
    no_active_promo: int = 0
    failed: int = 0
    disabled: bool = False
    mirror_unavailable: bool = False
    failed_items: List[int] = field(default_factory=list)


def enqueue_mlas(db: Session, mlas: Iterable[str]) -> EnqueueResult:
    """Queues the items of `mlas` (one row per item). Does not commit: the caller owns the
    transaction. MLAs without a `PublicacionML` row are returned as unknown and queue nothing."""
    wanted = list(dict.fromkeys(mlas))
    mla_to_item: Dict[str, int] = {
        mla: item_id
        for mla, item_id in db.query(PublicacionML.mla, PublicacionML.item_id).filter(PublicacionML.mla.in_(wanted))
        if item_id is not None
    }
    item_ids = sorted(set(mla_to_item.values()))
    if item_ids:
        _upsert(db, item_ids)
    return EnqueueResult(items_queued=len(item_ids), unknown_mlas=[m for m in wanted if m not in mla_to_item])


def _upsert(db: Session, item_ids: List[int]) -> None:
    now = datetime.now(UTC)
    insert = pg_insert if db.get_bind().dialect.name == "postgresql" else sqlite_insert
    stmt = insert(PromoPriceRecomputeQueue).values(
        [{"item_id": item_id, "enqueued_at": now, "attempts": 0, "last_error": None} for item_id in item_ids]
    )
    stmt = stmt.on_conflict_do_update(
        index_elements=[PromoPriceRecomputeQueue.item_id],
        set_={"enqueued_at": stmt.excluded.enqueued_at, "attempts": 0, "last_error": None},
    )
    db.execute(stmt)


def fetch_activation_times(mlas: List[str]) -> Dict[str, datetime]:
    """ONE cross-DB query: the latest mirror `updated_at` of each MLA's candidate/started rows.
    Same rows and same meaning as `sync_promo_prices._fetch_newly_active_rows`."""
    if not mlas:
        return {}
    query = text("""
        SELECT mla, MAX(updated_at)
        FROM ml_item_promotions
        WHERE status IN ('candidate', 'started')
          AND mla IN :mlas
        GROUP BY mla
    """).bindparams(bindparam("mlas", expanding=True))
    with get_mlwebhook_engine().connect() as conn:
        rows = conn.execute(query, {"mlas": list(mlas)}).fetchall()
    return {row[0]: row[1] for row in rows if row[1] is not None}


def _claim(excluded: Set[int]) -> List[Tuple[int, datetime]]:
    with get_background_db() as db:
        query = db.query(PromoPriceRecomputeQueue.item_id, PromoPriceRecomputeQueue.enqueued_at).filter(
            PromoPriceRecomputeQueue.attempts < MAX_ATTEMPTS
        )
        if excluded:
            query = query.filter(PromoPriceRecomputeQueue.item_id.notin_(excluded))
        return [
            (item_id, enqueued_at)
            for item_id, enqueued_at in query.order_by(PromoPriceRecomputeQueue.enqueued_at).limit(BATCH_ITEMS)
        ]


def _same_request(item_id: int, enqueued_at: datetime):
    return (PromoPriceRecomputeQueue.item_id == item_id) & (PromoPriceRecomputeQueue.enqueued_at == enqueued_at)


def _mlas_of(item_id: int) -> List[str]:
    with get_background_db() as db:
        return [mla for (mla,) in db.query(PublicacionML.mla).filter(PublicacionML.item_id == item_id)]


def _dequeue(item_id: int, enqueued_at: datetime) -> None:
    with get_background_db() as db:
        db.query(PromoPriceRecomputeQueue).filter(_same_request(item_id, enqueued_at)).delete(synchronize_session=False)


def _recompute_one(item_id: int, enqueued_at: datetime, activation: datetime) -> None:
    with get_background_db() as db:
        recompute_item(db, item_id, now=activation)
        db.query(PromoPriceRecomputeQueue).filter(_same_request(item_id, enqueued_at)).delete(synchronize_session=False)


def _charge(item_id: int, enqueued_at: datetime, error: str) -> None:
    with get_background_db() as db:
        db.query(PromoPriceRecomputeQueue).filter(_same_request(item_id, enqueued_at)).update(
            {
                PromoPriceRecomputeQueue.attempts: PromoPriceRecomputeQueue.attempts + 1,
                PromoPriceRecomputeQueue.last_error: error[:_ERROR_MAX_CHARS],
            },
            synchronize_session=False,
        )


def drain(deadline: datetime) -> DrainResult:
    """Recomputes queued items until the queue is empty or `deadline` passes. Each item is
    processed at most once per call, so a failing or re-requested item waits for the next pass.
    Stops early, charging nothing, when the mirror cannot be read."""
    result = DrainResult()
    if not settings.PROMOS_WRITE_ENABLED:
        result.disabled = True
        return result

    seen: Set[int] = set()
    while datetime.now(UTC) < deadline:
        claims = _claim(seen)
        if not claims:
            break
        for item_id, enqueued_at in claims:
            if datetime.now(UTC) >= deadline:
                return result
            seen.add(item_id)
            mlas = _mlas_of(item_id)
            try:
                activation_times = fetch_activation_times(mlas)
            except Exception:  # noqa: BLE001 -- a dependency outage, not this item's fault
                logger.warning("promo_price.recompute: mirror unreadable, pass stopped", exc_info=True)
                result.mirror_unavailable = True
                return result
            if not activation_times:
                _dequeue(item_id, enqueued_at)
                result.no_active_promo += 1
                continue
            try:
                _recompute_one(item_id, enqueued_at, max(activation_times.values()))
            except Exception as exc:  # noqa: BLE001 -- one item's failure must not stop the others
                logger.warning("promo_price.recompute: item %s failed", item_id, exc_info=True)
                result.failed += 1
                result.failed_items.append(item_id)
                try:
                    _charge(item_id, enqueued_at, f"{type(exc).__name__}: {exc}")
                except Exception:  # noqa: BLE001
                    logger.error("promo_price.recompute: charging item %s failed", item_id, exc_info=True)
            else:
                result.recomputed += 1
    return result
