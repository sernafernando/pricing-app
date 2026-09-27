"""Pack-level all-or-nothing aggregation (ventas-ml-rediseno PR18, design
D13, spec `ml-order-breakdown` R36/R37, `ml-sales-kpi-aggregation` R16/R17).

`aggregate_pack_metrics` is the SINGLE place that sums `total_gauss` and
`costo_mercaderia` across a pack's member orders, all-or-nothing -- ANY
member missing a stored `ml_order_metrics` row makes the whole pack sum
`None`, never a partial sum over the members that do have one. Before this
module existed, `ml_ventas_ops.py`'s `obtener_operacion` and `listar_ventas`
each carried their own copy of this same rule.

`sum_all_or_nothing` is exported separately because `listar_ventas` already
holds its members' `total_gauss` values in memory (from the per-row query it
already ran) and has no reason to go back to the database through
`aggregate_pack_metrics` just to re-sum them.
"""

from __future__ import annotations

from dataclasses import dataclass
from decimal import Decimal
from typing import Optional, Sequence

from sqlalchemy.orm import Session

from app.services.order_metrics.read import read_stored_metrics


def sum_all_or_nothing(values: Sequence[Optional[Decimal]]) -> Optional[Decimal]:
    """Sums `values`, or `None` when the sequence is empty or ANY entry is
    `None` -- never a partial sum over the ones that are known."""
    values = list(values)
    if not values or any(v is None for v in values):
        return None
    total = Decimal("0")
    for v in values:
        total += v  # type: ignore[arg-type]
    return total


@dataclass(frozen=True)
class PackMetrics:
    """The pack-scoped counterpart of `OrderMetrics` (design D13, spec
    BREAKDOWN R36/R37): `total_gauss`/`costo_mercaderia` summed
    all-or-nothing across every member order, `markup_pct` derived from
    those two sums under the SAME never-invent discipline as order-level
    markup -- `None`, never `0`, whenever either sum is unknown or
    `costo_mercaderia` sums to exactly zero."""

    total_gauss: Optional[Decimal]
    costo_mercaderia: Optional[Decimal]
    markup_pct: Optional[Decimal]


def aggregate_pack_metrics(db: Session, order_ids: Sequence[int]) -> PackMetrics:
    """Bulk-reads the stored metrics for every `order_id` (one query, via
    `read_stored_metrics`) and sums `total_gauss`/`costo_mercaderia`
    all-or-nothing across them (spec BREAKDOWN R37). Degenerates naturally
    to a single member's own values when `order_ids` has exactly one entry
    (R40) -- no special-casing needed."""
    order_ids = list(order_ids)
    stored_by_order = read_stored_metrics(db, order_ids)

    if not order_ids or len(stored_by_order) != len(order_ids):
        # Either no members at all, or at least one member has no stored
        # row yet -- the pack sum is unknown, never a partial sum over the
        # others that DO have one.
        return PackMetrics(total_gauss=None, costo_mercaderia=None, markup_pct=None)

    total_gauss = sum_all_or_nothing([m.total_gauss for m in stored_by_order.values()])
    costo_mercaderia = sum_all_or_nothing([m.costo_mercaderia for m in stored_by_order.values()])

    markup_pct: Optional[Decimal] = None
    if total_gauss is not None and costo_mercaderia is not None and costo_mercaderia != 0:
        markup_pct = (total_gauss / costo_mercaderia) * Decimal("100")

    return PackMetrics(total_gauss=total_gauss, costo_mercaderia=costo_mercaderia, markup_pct=markup_pct)
