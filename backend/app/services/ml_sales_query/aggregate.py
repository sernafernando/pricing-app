"""Aggregation over the shared query layer's filtered scope (design D12,
spec `ml-sales-kpi-aggregation` R8, R14; SM R2/R3).

`aggregate_order_metrics` NEVER recomputes anything -- it reads bulk from
`order_metrics.read` (`read_stored_metrics`/`metrics_state_for_orders`),
the same authoritative reader PR7's listing/detail switch to, and sums over
the WHOLE filtered set in-process from those two bulk reads plus one bulk
read of the order rows themselves -- O(1) queries total, never a per-row
loop, matching the KPI endpoint's own no-LIMIT contract (design D12a
"Query-count / plan note").

Exclusion rule (design D9, spec KPI R8/R14, SM R2/R3): an order whose
`metrics_state` is `'recalculating'` or `'pending'` is counted (via
`recalculating_count`/`pending_count`) but excluded from EVERY sum in this
module, including `gross_billed` -- spec R14 defines KPI parity against
"exactly the rows the listing would show ... EXCLUDING rows in the
recalculating or pending state", with no carve-out for the raw order
fields. A `'failed'` (parked) order is likewise excluded from every sum and
reported via `failed_count` (design D9: "excluded from KPI sums").
`unresolved_neto_count`/`total_gauss_unresolved_count` are the honest
counterpart for a row that DID finish computing but came back with an
unresolvable value -- never a fabricated zero standing in for either kind
of "don't know" (SM R2/R3, orchestrator instructions).

K1 fix (blocking, money): `markup_weighted_pct`'s numerator
(SUM(total_gauss)) and denominator (SUM(costo_mercaderia)) must be summed
over the EXACT SAME population of orders -- an order contributes to
EITHER side only when it carries BOTH values. Skipped orders are counted,
never hidden, via `markup_skipped_count`. `total_gauss_sum` (a separate
measure, spec KPI R8) is NOT gated by this rule -- it still includes an
order's `total_gauss` whenever that value alone is present.
"""

from __future__ import annotations

from dataclasses import dataclass, field
from decimal import Decimal
from typing import Dict, Optional

from sqlalchemy.orm import Query, Session

from app.models.ml_orders_ops import MlOrdersOps
from app.services.order_metrics.read import metrics_state_for_orders, read_stored_metrics
from app.services.order_metrics.types import GaussStatus

# Orders in one of these states never contribute to any sum below -- see
# module docstring. `'failed'` is reported via `failed_count`, not lumped
# into `recalculating_count` (design D9: a parked order is never shown as
# recalculating forever).
_RECALCULATING_STATES = frozenset({"recalculating"})
_PENDING_STATES = frozenset({"pending"})
_FAILED_STATES = frozenset({"failed"})


@dataclass(frozen=True)
class AggregateResult:
    """Design D12 `aggregate.py` measures (spec KPI R8). Every count/sum
    field EXCLUDES `recalculating`/`pending`/`failed` orders (see module
    docstring); `recalculating_count`/`pending_count`/`failed_count`
    reconcile the difference against `orders_scanned` (spec R14: "listed
    rows = rows summed + recalculating_count + pending_count", extended
    here with `failed_count` for the same reason -- a parked order is
    listed too, just never summed)."""

    groups_count: int
    orders_scanned: int
    orders_count: int
    recalculating_count: int
    pending_count: int
    failed_count: int

    gross_billed_ars: Decimal
    # Non-ARS totals kept SEPARATE per currency -- summing them together
    # with the ARS figure, or with each other, produces a number with no
    # unit (design D12 "gross_billed (ARS; other currencies counted
    # separately)").
    gross_billed_other: Dict[str, Decimal] = field(default_factory=dict)

    neto_sum: Decimal = Decimal("0")
    neto_unknown_count: int = 0

    total_gauss_sum: Decimal = Decimal("0")
    total_gauss_ok_count: int = 0
    total_gauss_provisional_count: int = 0
    total_gauss_unresolved_count: int = 0

    # SUM(total_gauss) / SUM(costo_mercaderia) * 100 -- NEVER an average of
    # per-order percentages (design D12 explicit rule). `None` when the
    # costo denominator sums to zero or nothing summable exists, never a
    # fabricated 0%.
    markup_weighted_pct: Optional[Decimal] = None
    # K1: an order missing EITHER `total_gauss` OR `costo_mercaderia`
    # contributes to NEITHER side of the ratio above -- counted here,
    # never silently dropped.
    markup_skipped_count: int = 0


def aggregate_order_metrics(db: Session, listing_query: Query, group_key) -> AggregateResult:
    """Aggregates the WHOLE filtered set `listing_query` describes -- no
    `LIMIT`, no pagination (design D12a: the KPI endpoint has none). Reads
    every `MlOrdersOps` row the query matches (one bulk query), then the
    stored metrics for exactly those order_ids (two more bulk queries, via
    `order_metrics.read`) -- three queries total regardless of how many
    orders match."""
    orders = listing_query.with_entities(
        MlOrdersOps.order_id, MlOrdersOps.total_amount, MlOrdersOps.currency_id, group_key.label("group_key")
    ).all()

    orders_scanned = len(orders)
    group_keys = {row.group_key for row in orders}
    order_ids = [row.order_id for row in orders]

    states = metrics_state_for_orders(db, order_ids)
    metrics = read_stored_metrics(db, order_ids)

    recalculating_count = 0
    pending_count = 0
    failed_count = 0
    orders_count = 0

    gross_billed_ars = Decimal("0")
    gross_billed_other: Dict[str, Decimal] = {}

    neto_sum = Decimal("0")
    neto_unknown_count = 0

    total_gauss_sum = Decimal("0")
    total_gauss_ok_count = 0
    total_gauss_provisional_count = 0
    total_gauss_unresolved_count = 0

    costo_sum = Decimal("0")
    tg_sum_for_markup = Decimal("0")
    markup_skipped_count = 0

    for order in orders:
        state = states.get(order.order_id, "pending")
        if state in _RECALCULATING_STATES:
            recalculating_count += 1
            continue
        if state in _PENDING_STATES:
            pending_count += 1
            continue
        if state in _FAILED_STATES:
            failed_count += 1
            continue

        orders_count += 1

        if order.total_amount is not None:
            if order.currency_id == "ARS":
                gross_billed_ars += Decimal(order.total_amount)
            elif order.currency_id is not None:
                gross_billed_other[order.currency_id] = gross_billed_other.get(
                    order.currency_id, Decimal("0")
                ) + Decimal(order.total_amount)

        row = metrics.get(order.order_id)
        if row is None:
            # `metrics_state` said this order is neither recalculating,
            # pending nor failed, so a stored row is expected -- defensive,
            # never fabricated as if it were known.
            neto_unknown_count += 1
            continue

        if row.neto is not None:
            neto_sum += Decimal(row.neto)
        else:
            neto_unknown_count += 1

        if row.gauss_status == GaussStatus.OK:
            total_gauss_ok_count += 1
        elif row.gauss_status == GaussStatus.PROVISIONAL:
            total_gauss_provisional_count += 1
        elif row.gauss_status == GaussStatus.UNRESOLVED:
            total_gauss_unresolved_count += 1

        if row.total_gauss is not None:
            total_gauss_sum += Decimal(row.total_gauss)

        # K1: only an order carrying BOTH values may contribute to EITHER
        # side of the weighted markup ratio -- summing the numerator and
        # denominator over two different populations (this order's
        # total_gauss with no matching costo, or vice versa) produces a
        # ratio that corresponds to nothing.
        if row.total_gauss is not None and row.costo_mercaderia is not None:
            tg_sum_for_markup += Decimal(row.total_gauss)
            costo_sum += Decimal(row.costo_mercaderia)
        else:
            markup_skipped_count += 1

    markup_weighted_pct: Optional[Decimal] = None
    if costo_sum != 0:
        markup_weighted_pct = (tg_sum_for_markup / costo_sum) * Decimal("100")

    return AggregateResult(
        groups_count=len(group_keys),
        orders_scanned=orders_scanned,
        orders_count=orders_count,
        recalculating_count=recalculating_count,
        pending_count=pending_count,
        failed_count=failed_count,
        gross_billed_ars=gross_billed_ars,
        gross_billed_other=gross_billed_other,
        neto_sum=neto_sum,
        neto_unknown_count=neto_unknown_count,
        total_gauss_sum=total_gauss_sum,
        total_gauss_ok_count=total_gauss_ok_count,
        total_gauss_provisional_count=total_gauss_provisional_count,
        total_gauss_unresolved_count=total_gauss_unresolved_count,
        markup_weighted_pct=markup_weighted_pct,
        markup_skipped_count=markup_skipped_count,
    )
