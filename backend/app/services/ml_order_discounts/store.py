"""Database side of the per-sale discounts ingestion: which orders are pending, the fetch rows and the back-off.

Pending = an order with at least one payment carrying `coupon_amount > 0` in a relevant status, and no
`ml_order_discounts` row that is settled (`ok`, `none`, or `error` after `MAX_ATTEMPTS`). Newest sale first, so
the daily sales are fetched before the backfill of older ones. Each order is asked for once: a later refund does
not change the discounts ML applied to the sale.
"""

from __future__ import annotations

from datetime import datetime, timedelta
from typing import Any, Optional

from sqlalchemy import and_, delete, exists, func, null, or_, select
from sqlalchemy.dialects.postgresql import insert as pg_insert
from sqlalchemy.orm import Session
from sqlalchemy.sql.elements import ColumnElement

from app.models.ml_order_discounts import MlOrderDiscountLine, MlOrderDiscounts, MlOrderDiscountsState
from app.models.ml_payments import MlPaymentOps
from app.services.ml_order_discounts import mapper
from app.services.ml_ventas_desglose.breakdown_service import RELEVANT_PAYMENT_STATUSES

MAX_ATTEMPTS = 5
STATE_ID = 1
BACKOFF_BASE_SECONDS = 60.0
# An error is asked again only after this wait, so a transient ML outage cannot spend every attempt in minutes.
ERROR_RETRY = timedelta(hours=1)
BACKOFF_CAP_SECONDS = 3600.0
RETRY_AFTER_CAP_SECONDS = 86400.0


def _settled(now: Optional[datetime] = None) -> ColumnElement[bool]:
    """Settled orders are never asked again; with `now`, an `error` asked less than `ERROR_RETRY` ago also waits."""
    done = or_(MlOrderDiscounts.status != mapper.ERROR, MlOrderDiscounts.attempts >= MAX_ATTEMPTS)
    if now is not None:
        done = or_(done, MlOrderDiscounts.fetched_at > now - ERROR_RETRY)
    return exists().where(MlOrderDiscounts.order_id == MlPaymentOps.order_id, done)


def _pending_filter(now: Optional[datetime] = None) -> ColumnElement[bool]:
    return and_(
        MlPaymentOps.coupon_amount > 0,
        MlPaymentOps.status.in_(sorted(RELEVANT_PAYMENT_STATUSES)),
        ~_settled(now),
    )


def pending_orders(db: Session, limit: int, now: datetime) -> list[int]:
    """The orders to ask for now: pending and, for an earlier error, past its `ERROR_RETRY` wait."""
    if limit <= 0:
        return []
    newest = func.max(MlPaymentOps.date_approved)
    # Orders never asked first, retries after: a retried order (an error, a transport failure) never stays at
    # the head of the queue ahead of the ones not asked yet.
    asked = exists().where(MlOrderDiscounts.order_id == MlPaymentOps.order_id)
    stmt = (
        select(MlPaymentOps.order_id)
        .where(_pending_filter(now))
        .group_by(MlPaymentOps.order_id)
        .order_by(func.bool_or(asked).asc(), newest.desc().nulls_last(), MlPaymentOps.order_id.desc())
        .limit(limit)
    )
    return list(db.execute(stmt).scalars())


def pending_count(db: Session) -> int:
    """Every order not settled yet, errors waiting for their retry included (the backfill progress)."""
    stmt = select(func.count(func.distinct(MlPaymentOps.order_id))).where(_pending_filter())
    return int(db.execute(stmt).scalar() or 0)


def write_fetch(db: Session, order_id: int, status: str, http_status: int, body: Any, at: datetime) -> None:
    """Upsert the order's fetch and replace its lines. An `error` keeps counting attempts; `ok`/`none` settle it."""
    # `null()`: a missing body is SQL NULL (`body IS NULL`), never the JSON value `null`.
    values = {
        "order_id": order_id,
        "status": status,
        "http_status": http_status,
        "body": null() if body is None else body,
        "fetched_at": at,
    }
    stmt = pg_insert(MlOrderDiscounts).values(**values, attempts=1)
    db.execute(
        stmt.on_conflict_do_update(
            index_elements=["order_id"],
            set_={
                **{k: stmt.excluded[k] for k in values if k != "order_id"},
                "attempts": MlOrderDiscounts.attempts + 1,
            },
        )
    )
    db.execute(delete(MlOrderDiscountLine).where(MlOrderDiscountLine.order_id == order_id))
    lines = mapper.map_lines(order_id, body) if status == mapper.OK else []
    if lines:
        db.execute(pg_insert(MlOrderDiscountLine).values([vars(line) for line in lines]))


def defer(db: Session, order_id: int, at: datetime) -> None:
    """Send an order behind the others for `ERROR_RETRY` without counting an attempt: a transport failure is not
    the order's fault, but an order that always times out must not hold the queue (status `error`, attempts kept)."""
    stmt = pg_insert(MlOrderDiscounts).values(order_id=order_id, status=mapper.ERROR, attempts=0, fetched_at=at)
    db.execute(stmt.on_conflict_do_update(index_elements=["order_id"], set_={"fetched_at": at}))


def backoff_until(db: Session) -> Optional[datetime]:
    return db.execute(select(MlOrderDiscountsState.backoff_until).where(MlOrderDiscountsState.id == STATE_ID)).scalar()


def backoff_seconds(consecutive_429: int, retry_after: Optional[float] = None) -> float:
    """60 s doubling per consecutive 429 run, capped at one hour; never shorter than ML's `Retry-After`, which is
    honored up to a day (a bigger value is taken as a broken header, not a request to stop for longer)."""
    exponent = min(max(consecutive_429 - 1, 0), 16)  # 60 s * 2**16 is far past the cap; never overflows a float
    delay = min(BACKOFF_BASE_SECONDS * 2**exponent, BACKOFF_CAP_SECONDS)
    return max(delay, min(retry_after or 0.0, RETRY_AFTER_CAP_SECONDS))


def record_429(db: Session, now: datetime, retry_after: Optional[float] = None) -> tuple[int, datetime]:
    """Count one more consecutive 429 run and push `backoff_until`; returns both."""
    current = db.execute(
        select(MlOrderDiscountsState.consecutive_429).where(MlOrderDiscountsState.id == STATE_ID)
    ).scalar()
    count = (current or 0) + 1
    until = now + timedelta(seconds=backoff_seconds(count, retry_after))
    stmt = pg_insert(MlOrderDiscountsState).values(id=STATE_ID, consecutive_429=count, backoff_until=until)
    db.execute(
        stmt.on_conflict_do_update(index_elements=["id"], set_={"consecutive_429": count, "backoff_until": until})
    )
    return count, until


def clear_backoff(db: Session) -> None:
    stmt = pg_insert(MlOrderDiscountsState).values(id=STATE_ID, consecutive_429=0, backoff_until=None)
    db.execute(stmt.on_conflict_do_update(index_elements=["id"], set_={"consecutive_429": 0, "backoff_until": None}))
