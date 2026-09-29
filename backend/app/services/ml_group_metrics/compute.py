"""Group-level Gauss metrics compute (ventas-ml-rediseno PR20.T7/T8, design
D7, spec `ml-order-stored-metrics` R9/R10, `ml-sales-kpi-aggregation` R18-R20).

`recompute_group_metrics` is the SINGLE producer of `GroupMetrics`: for
each `group_key` it reads the group's CURRENT membership from
`ml_orders_ops` (never a cached member list -- a member can have changed
pack since the group was last computed), sums the per-member stored values
all-or-nothing (reusing `aggregate_pack_metrics`'s core --
`ml_ventas_desglose/pack_aggregation.py` -- so there is only ONE summation
formula), and derives `gauss_status` via `group_gauss_status`.

A group with any member that is not resolved (no stored row yet, a dirty
row pending recompute, or parked) resolves to `gauss_status='unresolved'`
or `'recalculating'` with every numeric field `None` -- NEVER a partial
sum over the members that happen to be ready (SM R10, KPI R19).
"""

from __future__ import annotations

from dataclasses import dataclass, field
from datetime import datetime, timezone
from decimal import Decimal
from typing import Dict, List, Optional, Sequence

from sqlalchemy import func
from sqlalchemy.orm import Session

from app.models.ml_orders_ops import MlOrdersOps
from app.services.ml_group_metrics.state import group_gauss_status
from app.services.ml_ventas_desglose.pack_aggregation import sum_all_or_nothing
from app.services.order_metrics.constants import CURRENT_FORMULA_VERSION
from app.services.order_metrics.read import metrics_state_for_orders, read_stored_metrics


@dataclass(frozen=True)
class GroupMetrics:
    """One group's computed Gauss metrics -- the return value of
    `recompute_group_metrics`, consumed by `store.store_group_metrics`."""

    group_key: str
    neto: Optional[Decimal]
    neto_sin_iva: Optional[Decimal]
    costo_mercaderia: Optional[Decimal]
    total_gauss: Optional[Decimal]
    markup_pct: Optional[Decimal]
    gauss_status: str
    gross_amount: Optional[Decimal] = None
    currency_id: Optional[str] = None
    member_order_ids: List[int] = field(default_factory=list)
    group_date: Optional[datetime] = None
    formula_version: int = CURRENT_FORMULA_VERSION
    computed_at: datetime = field(default_factory=lambda: datetime.now(timezone.utc))


def _parse_group_key(group_key: str) -> tuple[str, int]:
    """`"p:<pack_id>"` / `"o:<order_id>"` -- the exact format
    `_group_key_expr()` produces (`ml_sales_query/filters.py`)."""
    kind, _, raw_id = group_key.partition(":")
    if kind not in ("p", "o") or not raw_id:
        raise ValueError(f"malformed group_key: {group_key!r}")
    return kind, int(raw_id)


def _current_member_order_ids(db: Session, group_key: str) -> List[int]:
    kind, group_id = _parse_group_key(group_key)
    if kind == "p":
        rows = db.query(MlOrdersOps.order_id).filter(MlOrdersOps.pack_id == group_id).all()
        return sorted(r.order_id for r in rows)
    # kind == "o": a standalone order IS the group; it may since have
    # joined a pack (in which case it is no longer this group's member --
    # the caller's fanout/cleanup, T15-T22, handles that transition), but
    # `recompute_group_metrics` itself only ever reports what is CURRENTLY
    # true: this exact order, if it still exists and is still standalone.
    row = db.query(MlOrdersOps.order_id).filter(MlOrdersOps.order_id == group_id, MlOrdersOps.pack_id.is_(None)).first()
    return [row.order_id] if row else []


def _group_date(db: Session, member_order_ids: Sequence[int]) -> Optional[datetime]:
    """Group-level date (KPI R20): the MIN `date_created` across the
    group's current members -- a pack straddling a date-filter boundary is
    included/excluded as ONE whole pack, never split (PR20.T24/T25)."""
    if not member_order_ids:
        return None
    # An aggregate MIN, deliberately, NOT `ORDER BY date_created ASC LIMIT 1`.
    # `date_created` is nullable, and ASC puts NULLs FIRST on SQLite and LAST
    # on Postgres -- so the ordering form returns the real date in production
    # and `None` in the tests, which is the worst shape of bug: invisible
    # exactly where it would be caught. SQL `MIN()` ignores NULLs by
    # definition on both engines, which removes the question instead of
    # answering it with a `nullslast()` someone can drop later.
    return db.query(func.min(MlOrdersOps.date_created)).filter(MlOrdersOps.order_id.in_(member_order_ids)).scalar()


def _gross_amount(db: Session, member_order_ids: Sequence[int]) -> tuple[Optional[Decimal], Optional[str]]:
    """The group's gross billed and the currency it is expressed in.

    BOTH are `None` unless every member shares ONE currency and every
    member's `total_amount` is known. That is the same rule `listar_ventas`
    applies to a pack row, and its comment gives the reason better than this
    one could: adding ARS to USD produces a number that means nothing, and a
    mixed pack rendering a numeric amount beside an honest null would read as
    MORE trustworthy than the null, not less.

    Returning the pair together is deliberate: an amount without its currency
    is exactly the misleading value the gate exists to prevent, so there is no
    way to get one without the other.
    """
    filas = (
        db.query(MlOrdersOps.total_amount, MlOrdersOps.currency_id)
        .filter(MlOrdersOps.order_id.in_(member_order_ids))
        .all()
    )
    if not filas or len(filas) != len(member_order_ids):
        return None, None

    monedas = {c for _a, c in filas}
    if len(monedas) != 1 or None in monedas:
        return None, None

    montos = [a for a, _c in filas]
    if any(a is None for a in montos):
        return None, None

    return sum(Decimal(str(a)) for a in montos), monedas.pop()


def recompute_group_metrics(db: Session, group_keys: Sequence[str]) -> Dict[str, GroupMetrics]:
    """Computes `GroupMetrics` for every `group_key` in `group_keys`. A
    `group_key` whose current membership is empty (the group no longer
    exists -- SM R14) is simply ABSENT from the result, never a fabricated
    empty-group record; the caller (T22e's orphan cleanup) is responsible
    for deleting any existing stored row in that case."""
    result: Dict[str, GroupMetrics] = {}
    now = datetime.now(timezone.utc)

    for group_key in group_keys:
        member_order_ids = _current_member_order_ids(db, group_key)
        if not member_order_ids:
            continue

        states = metrics_state_for_orders(db, member_order_ids)
        # `states` only carries entries for order_ids resolvable by
        # `metrics_state_for_orders` (it defaults every requested id to
        # 'pending' when it has neither a dirty nor a stored row -- see
        # its own loop) -- request every member explicitly so a truly
        # unseen member still resolves to 'pending', not a KeyError.
        member_states = [states.get(order_id, "pending") for order_id in member_order_ids]
        gauss_status = group_gauss_status(member_states)

        if gauss_status in ("unresolved", "recalculating", "failed"):
            # `ml_group_metrics.gauss_status` is CHECK-constrained to
            # ('ok', 'provisional', 'unresolved') -- the SAME narrower
            # vocabulary as `ml_order_metrics.gauss_status`. `recalculating`
            # and `failed` are `group_gauss_status`'s own (wider) return
            # values, mirroring `metrics_state_for_orders`'s per-order
            # vocabulary; they collapse to the stored column's 'unresolved'
            # here -- the WHY a group is not resolvable lives in the
            # per-member dirty-queue state a future reader can still derive
            # on demand, never a fabricated numeric value either way.
            result[group_key] = GroupMetrics(
                group_key=group_key,
                neto=None,
                neto_sin_iva=None,
                costo_mercaderia=None,
                total_gauss=None,
                markup_pct=None,
                gauss_status="unresolved",
                member_order_ids=member_order_ids,
                group_date=_group_date(db, member_order_ids),
                computed_at=now,
            )
            continue

        stored_by_order = read_stored_metrics(db, member_order_ids)
        total_gauss = sum_all_or_nothing([m.total_gauss for m in stored_by_order.values()])
        costo_mercaderia = sum_all_or_nothing([m.costo_mercaderia for m in stored_by_order.values()])
        neto = sum_all_or_nothing([m.neto for m in stored_by_order.values()])
        neto_sin_iva = sum_all_or_nothing([m.neto_sin_iva for m in stored_by_order.values()])

        gross_amount, currency_id = _gross_amount(db, member_order_ids)

        markup_pct: Optional[Decimal] = None
        if total_gauss is not None and costo_mercaderia is not None and costo_mercaderia != 0:
            markup_pct = (total_gauss / costo_mercaderia) * Decimal("100")

        result[group_key] = GroupMetrics(
            group_key=group_key,
            neto=neto,
            neto_sin_iva=neto_sin_iva,
            costo_mercaderia=costo_mercaderia,
            total_gauss=total_gauss,
            markup_pct=markup_pct,
            gauss_status=gauss_status,
            gross_amount=gross_amount,
            currency_id=currency_id,
            member_order_ids=member_order_ids,
            group_date=_group_date(db, member_order_ids),
            computed_at=now,
        )

    return result
