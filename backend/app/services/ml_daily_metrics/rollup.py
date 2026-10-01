"""Writer of `ml_product_daily_metrics` (ODD `metricas-ml-tablero` T2).

The unit of work is an (MLA, day) BUCKET: every product row of that MLA on
that business day is recomputed FROM SOURCE and replaced, and a row whose
source vanished (the sale moved day, got cancelled) is deleted. Never an
incremental +/-: a re-store can never double count, and a bucket that ever
drifts heals on the next store that touches it (or on the backfill script).

Source, per sold item:
- the GROUP's accreditation timestamp (`ml_group_metrics.group_date`, the
  Ventas ML day rule), bucketed by the business-timezone date;
- quantity and unit price from `ml_order_items_ops`;
- the product and frozen unit cost from `ml_order_item_costos`;
- the order's stored Total Gauss and cost of goods from `ml_order_metrics`,
  split across the order's items by frozen-cost share.

A sale cancelled WITHOUT Mercado Libre covering it is not a sale; one ML
covered (`covered_by_marketplace`) is -- the money arrived, same rule as the
Ventas ML "Cubierta por ML" status.

NEVER commits: the caller owns the transaction (same contract as
`order_metrics.store.store_order_metrics`).
"""

from __future__ import annotations

from collections import defaultdict
from dataclasses import dataclass, field
from datetime import date, datetime, time, timedelta, timezone
from decimal import ROUND_HALF_UP, Decimal
from typing import Dict, Iterable, List, Optional, Set, Tuple
from zoneinfo import ZoneInfo

from sqlalchemy import String, and_, case, cast, literal, or_, tuple_
from sqlalchemy.dialects import postgresql, sqlite
from sqlalchemy.orm import Session

from app.core.config import settings
from app.core.constants import BUSINESS_TIMEZONE
from app.models.ml_daily_metrics import MlProductDailyMetrics
from app.models.ml_group_metrics import MlGroupMetrics
from app.models.ml_order_item_costo import MlOrderItemCosto
from app.models.ml_order_metrics import MlOrderMetrics
from app.models.ml_orders_ops import MlOrderItemOps, MlOrdersOps

BUSINESS_TZ = ZoneInfo(BUSINESS_TIMEZONE)
NO_PRODUCT = 0
CENT = Decimal("0.01")
# Statuses whose stored Total Gauss/cost are usable money (Ventas ML counts
# provisional figures by default; `unresolved` carries no number).
USABLE_GAUSS_STATUSES = ("ok", "provisional")

Bucket = Tuple[str, date]
RowKey = Tuple[int, str, date]


def business_day(moment: datetime) -> date:
    """The business-timezone calendar day of a timestamp (naive = UTC, which
    is what SQLite hands back for a tz-aware column)."""
    if moment.tzinfo is None:
        moment = moment.replace(tzinfo=timezone.utc)
    return moment.astimezone(BUSINESS_TZ).date()


def _day_bounds(day: date) -> Tuple[datetime, datetime]:
    # In UTC: SQLite drops the offset of a bound tz-aware value, so a
    # business-midnight bound would silently compare as UTC midnight there.
    start = datetime.combine(day, time.min, tzinfo=BUSINESS_TZ).astimezone(timezone.utc)
    end = datetime.combine(day + timedelta(days=1), time.min, tzinfo=BUSINESS_TZ).astimezone(timezone.utc)
    return start, end


def _group_key_expr():
    return case(
        (MlOrdersOps.pack_id.isnot(None), literal("p:") + cast(MlOrdersOps.pack_id, String)),
        else_=literal("o:") + cast(MlOrdersOps.order_id, String),
    )


def _insert(db: Session, table):
    if db.get_bind().dialect.name == "postgresql":
        return postgresql.insert(table)
    return sqlite.insert(table)


@dataclass
class _Acc:
    units: int = 0
    gross_ars: Decimal = Decimal("0")
    total_gauss: Decimal = Decimal("0")
    costo: Decimal = Decimal("0")
    orders: Set[int] = field(default_factory=set)
    unresolved: Set[int] = field(default_factory=set)
    last_sale_at: Optional[datetime] = None


@dataclass
class _Item:
    mla: str
    product: int
    quantity: int
    unit_price: Optional[Decimal]
    weight: Optional[Decimal]


def _orders_in_buckets(db: Session, buckets: Set[Bucket]) -> Dict[int, datetime]:
    """`order_id -> group accreditation timestamp` for every order that sold
    one of the buckets' MLAs on one of its days."""
    mlas = sorted({mla for mla, _day in buckets})
    days_set = {day for _mla, day in buckets}
    days = sorted(days_set)
    start, _ = _day_bounds(days[0])
    _, end = _day_bounds(days[-1])
    q = (
        db.query(MlOrdersOps.order_id, MlGroupMetrics.group_date)
        .join(MlOrderItemOps, MlOrderItemOps.order_id == MlOrdersOps.order_id)
        .join(MlGroupMetrics, MlGroupMetrics.group_key == _group_key_expr())
        .filter(
            MlOrderItemOps.item_id.in_(mlas),
            MlGroupMetrics.group_date >= start,
            MlGroupMetrics.group_date < end,
        )
    )
    if settings.ML_USER_ID:
        q = q.filter(MlOrdersOps.seller_id == int(settings.ML_USER_ID))
    return {
        order_id: group_date
        for order_id, group_date in q.distinct().all()
        if group_date is not None and business_day(group_date) in days_set
    }


def _compute(db: Session, buckets: Set[Bucket]) -> Dict[RowKey, _Acc]:
    order_dates = _orders_in_buckets(db, buckets)
    if not order_dates:
        return {}
    order_ids = list(order_dates)

    orders = {
        o.order_id: o
        for o in db.query(
            MlOrdersOps.order_id, MlOrdersOps.status, MlOrdersOps.covered_by_marketplace, MlOrdersOps.currency_id
        ).filter(MlOrdersOps.order_id.in_(order_ids))
    }
    metrics = {
        m.order_id: m
        for m in db.query(
            MlOrderMetrics.order_id,
            MlOrderMetrics.total_gauss,
            MlOrderMetrics.costo_mercaderia,
            MlOrderMetrics.gauss_status,
        ).filter(MlOrderMetrics.order_id.in_(order_ids))
    }
    items_by_order: Dict[int, List[_Item]] = defaultdict(list)
    item_rows = (
        db.query(
            MlOrderItemOps.order_id,
            MlOrderItemOps.item_id,
            MlOrderItemOps.quantity,
            MlOrderItemOps.unit_price,
            MlOrderItemCosto.producto_item_id,
            MlOrderItemCosto.costo_unitario_ars,
        )
        .outerjoin(
            MlOrderItemCosto,
            and_(
                MlOrderItemCosto.order_id == MlOrderItemOps.order_id,
                MlOrderItemCosto.item_id == MlOrderItemOps.item_id,
                or_(
                    MlOrderItemCosto.variation_id == MlOrderItemOps.variation_id,
                    and_(MlOrderItemCosto.variation_id.is_(None), MlOrderItemOps.variation_id.is_(None)),
                ),
            ),
        )
        .filter(MlOrderItemOps.order_id.in_(order_ids))
        .order_by(MlOrderItemOps.order_id, MlOrderItemOps.id)
    )
    for row in item_rows:
        quantity = row.quantity or 0
        weight = (Decimal(row.costo_unitario_ars) * quantity) if row.costo_unitario_ars is not None else None
        items_by_order[row.order_id].append(
            _Item(
                mla=row.item_id,
                product=row.producto_item_id if row.producto_item_id is not None else NO_PRODUCT,
                quantity=quantity,
                unit_price=Decimal(row.unit_price) if row.unit_price is not None else None,
                weight=weight,
            )
        )

    acc: Dict[RowKey, _Acc] = defaultdict(_Acc)
    for order_id, group_date in order_dates.items():
        order = orders.get(order_id)
        if order is None or (order.status == "cancelled" and not order.covered_by_marketplace):
            continue
        day = business_day(group_date)
        items = items_by_order.get(order_id, [])
        if not items:
            continue
        m = metrics.get(order_id)
        usable = (
            m is not None
            and m.gauss_status in USABLE_GAUSS_STATUSES
            and m.total_gauss is not None
            and m.costo_mercaderia is not None
        )
        shares = _shares(items) if usable else None
        for index, item in enumerate(items):
            if (item.mla, day) not in buckets:
                continue
            a = acc[(item.product, item.mla, day)]
            a.units += item.quantity
            if item.unit_price is not None and (order.currency_id or "ARS") == "ARS":
                a.gross_ars += item.unit_price * item.quantity
            a.orders.add(order_id)
            if usable:
                a.total_gauss += Decimal(m.total_gauss) * shares[index]
                a.costo += Decimal(m.costo_mercaderia) * shares[index]
            else:
                a.unresolved.add(order_id)
            if a.last_sale_at is None or group_date > a.last_sale_at:
                a.last_sale_at = group_date
    return acc


def _shares(items: List[_Item]) -> List[Decimal]:
    """Each item's fraction of the order: its frozen cost (`costo_unitario_ars
    x quantity`) over the order's. A lone item takes it all; when the weights
    are unknown or zero, quantity decides (never a division by zero)."""
    if len(items) == 1:
        return [Decimal("1")]
    weights = [item.weight for item in items]
    if any(w is None for w in weights) or sum(weights) == 0:
        weights = [Decimal(item.quantity) for item in items]
    total = sum(weights)
    if total == 0:
        return [Decimal("1") / len(items)] * len(items)
    return [Decimal(w) / total for w in weights]


def refresh_rollup(db: Session, buckets: Iterable[Bucket]) -> int:
    """Recomputes every (MLA, day) bucket in `buckets` from source and makes
    the table match: upserts the rows that have sales, deletes the ones that
    no longer do. Returns how many rows it wrote. NEVER commits."""
    buckets = {(mla, day) for mla, day in buckets if mla and day is not None}
    if not buckets:
        return 0
    computed = _compute(db, buckets)

    keep = set(computed)
    existing = (
        db.query(
            MlProductDailyMetrics.id,
            MlProductDailyMetrics.product_item_id,
            MlProductDailyMetrics.mla,
            MlProductDailyMetrics.day,
        )
        .filter(tuple_(MlProductDailyMetrics.mla, MlProductDailyMetrics.day).in_(sorted(buckets)))
        .all()
    )
    stale_ids = [row.id for row in existing if (row.product_item_id, row.mla, row.day) not in keep]
    if stale_ids:
        db.query(MlProductDailyMetrics).filter(MlProductDailyMetrics.id.in_(stale_ids)).delete(
            synchronize_session=False
        )

    if not computed:
        return 0
    now = datetime.now(timezone.utc)
    rows = [
        {
            "product_item_id": product,
            "mla": mla,
            "day": day,
            "units": a.units,
            "gross_ars": a.gross_ars.quantize(CENT, ROUND_HALF_UP),
            "total_gauss": a.total_gauss.quantize(CENT, ROUND_HALF_UP),
            "costo": a.costo.quantize(CENT, ROUND_HALF_UP),
            "orders": len(a.orders),
            "unresolved_orders": len(a.unresolved),
            "last_sale_at": a.last_sale_at,
            "updated_at": now,
        }
        # Sorted: two workers refreshing overlapping buckets lock rows in the
        # same order and queue instead of deadlocking.
        for (product, mla, day), a in sorted(computed.items())
    ]
    stmt = _insert(db, MlProductDailyMetrics.__table__)
    stmt = stmt.on_conflict_do_update(
        index_elements=["product_item_id", "mla", "day"],
        set_={col: stmt.excluded[col] for col in rows[0] if col not in ("product_item_id", "mla", "day")},
    )
    db.execute(stmt, rows)
    return len(rows)


def buckets_for_groups(
    db: Session, group_keys: Iterable[str], previous_dates: Dict[str, Optional[datetime]]
) -> Set[Bucket]:
    """The (MLA, day) buckets a store of these groups can have touched: every
    MLA their member orders sold, on the group's CURRENT day and on the day it
    had BEFORE this store (`previous_dates`), so a sale that moved day is
    taken out of its old bucket too."""
    group_keys = list(group_keys)
    if not group_keys:
        return set()
    groups = db.query(MlGroupMetrics.group_key, MlGroupMetrics.group_date, MlGroupMetrics.member_order_ids).filter(
        MlGroupMetrics.group_key.in_(group_keys)
    )
    current: Dict[str, Optional[datetime]] = {}
    group_of_order: Dict[int, str] = {}
    for key, group_date, members in groups:
        current[key] = group_date
        for order_id in members or ():
            group_of_order[int(order_id)] = key
    mlas_by_group: Dict[str, Set[str]] = defaultdict(set)
    if group_of_order:
        items = db.query(MlOrderItemOps.order_id, MlOrderItemOps.item_id).filter(
            MlOrderItemOps.order_id.in_(list(group_of_order))
        )
        for order_id, mla in items:
            mlas_by_group[group_of_order[order_id]].add(mla)

    buckets: Set[Bucket] = set()
    for key in group_keys:
        days = {business_day(d) for d in (current.get(key), previous_dates.get(key)) if d is not None}
        buckets.update((mla, day) for mla in mlas_by_group.get(key, ()) for day in days)
    return buckets


def _stored_snapshot(db: Session, buckets: Set[Bucket]) -> Dict[RowKey, tuple]:
    rows = db.query(MlProductDailyMetrics).filter(
        tuple_(MlProductDailyMetrics.mla, MlProductDailyMetrics.day).in_(sorted(buckets))
    )
    return {
        (r.product_item_id, r.mla, r.day): (
            r.units,
            Decimal(r.gross_ars or 0).quantize(CENT),
            Decimal(r.total_gauss or 0).quantize(CENT),
            Decimal(r.costo or 0).quantize(CENT),
            r.orders,
            r.unresolved_orders,
        )
        for r in rows
    }


def stale_buckets(db: Session, buckets: Iterable[Bucket]) -> Set[Bucket]:
    """The buckets whose stored rows differ from what `refresh_rollup` would
    write now (a missing row, a ghost row, or a different sum). Read-only:
    what the backfill's dry run and its `remaining` re-scan report."""
    buckets = set(buckets)
    if not buckets:
        return set()
    computed = {
        key: (
            a.units,
            a.gross_ars.quantize(CENT, ROUND_HALF_UP),
            a.total_gauss.quantize(CENT, ROUND_HALF_UP),
            a.costo.quantize(CENT, ROUND_HALF_UP),
            len(a.orders),
            len(a.unresolved),
        )
        for key, a in _compute(db, buckets).items()
    }
    stored = _stored_snapshot(db, buckets)
    differing = set(computed) ^ set(stored)
    differing |= {key for key in computed.keys() & stored.keys() if computed[key] != stored[key]}
    return {(mla, day) for (_product, mla, day) in differing}
