"""Database side of the per-sale discounts ingestion: which orders are pending, the fetch rows and the back-off.

Pending = an order with at least one payment carrying `coupon_amount > 0` in a relevant status, and no
`ml_order_discounts` row that is settled (`ok`, `none`, or `error` after `MAX_ATTEMPTS`). Newest sale first, so
the daily sales are fetched before the backfill of older ones. Each order is asked for once: a later refund does
not change the discounts ML applied to the sale.
"""

from __future__ import annotations

from datetime import datetime, timedelta
from typing import Any, Optional

from sqlalchemy import and_, delete, exists, func, or_, select
from sqlalchemy.dialects.postgresql import insert as pg_insert
from sqlalchemy.orm import Session

from app.models.ml_order_discounts import MlOrderDiscountLine, MlOrderDiscounts, MlOrderDiscountsState
from app.models.ml_payments import MlPaymentOps
from app.services.ml_order_discounts import mapper
from app.services.ml_ventas_desglose.breakdown_service import RELEVANT_PAYMENT_STATUSES

MAX_ATTEMPTS = 5
STATE_ID = 1
BACKOFF_BASE_SECONDS = 60.0
BACKOFF_CAP_SECONDS = 3600.0


def _settled():  # noqa: ANN202 -- a SQL boolean expression
    return exists().where(
        MlOrderDiscounts.order_id == MlPaymentOps.order_id,
        or_(MlOrderDiscounts.status != mapper.ERROR, MlOrderDiscounts.attempts >= MAX_ATTEMPTS),
    )


def _pending_filter():  # noqa: ANN202
    return and_(
        MlPaymentOps.coupon_amount > 0,
        MlPaymentOps.status.in_(sorted(RELEVANT_PAYMENT_STATUSES)),
        ~_settled(),
    )


def pending_orders(db: Session, limit: int) -> list[int]:
    if limit <= 0:
        return []
    newest = func.max(MlPaymentOps.date_approved)
    stmt = (
        select(MlPaymentOps.order_id)
        .where(_pending_filter())
        .group_by(MlPaymentOps.order_id)
        .order_by(newest.desc().nulls_last(), MlPaymentOps.order_id.desc())
        .limit(limit)
    )
    return list(db.execute(stmt).scalars())


def pending_count(db: Session) -> int:
    stmt = select(func.count(func.distinct(MlPaymentOps.order_id))).where(_pending_filter())
    return int(db.execute(stmt).scalar() or 0)


def write_fetch(db: Session, order_id: int, status: str, http_status: int, body: Any, at: datetime) -> None:
    """Upsert the order's fetch and replace its lines. An `error` keeps counting attempts; `ok`/`none` settle it."""
    values = {"order_id": order_id, "status": status, "http_status": http_status, "body": body, "fetched_at": at}
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


def backoff_until(db: Session) -> Optional[datetime]:
    return db.execute(select(MlOrderDiscountsState.backoff_until).where(MlOrderDiscountsState.id == STATE_ID)).scalar()


def backoff_seconds(consecutive_429: int, retry_after: Optional[float] = None) -> float:
    """60 s doubling per consecutive 429 run, capped at one hour; never shorter than ML's `Retry-After`."""
    delay = min(BACKOFF_BASE_SECONDS * 2 ** (consecutive_429 - 1), BACKOFF_CAP_SECONDS)
    return max(delay, min(retry_after or 0.0, BACKOFF_CAP_SECONDS))


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
