"""Single resolver for "the day of this sale" (ODD
`ventas-ml-dia-por-acreditacion`, decision 2026-09-30 --
`odd/tasks/ventas-ml-dia-por-acreditacion.md`).

> Una venta entra en el día en que se ACREDITÓ su plata. Una venta sin
> plata acreditada no está en ningún día.

day = `MAX(date_approved)` over the RELEVANT payments
(`RELEVANT_PAYMENT_STATUSES` -- the SAME allow-list the Gauss chain and
`aggregate_order_metrics` use, never a second one) of ALL a group's
members. MAX, not MIN: the day answers "when can this ship", and a pack
cannot ship until its LAST member is paid -- so MAX is also how the two
levels (per-order, per-group) collapse into one rule.

This is deliberately NOT the same aggregate `_group_date`
(`ml_group_metrics/compute.py`) used before this change for
`date_created`: that one answers "when did this start" (MIN is right
there); this module answers "when can it ship" (MAX is right here).
Different question, different aggregate -- never unify them.

NEVER derive money-ness from `MlOrdersOps.payment_status`: it stores only
the FIRST payment's status (see `ml_sales_query/aggregate.py`'s own
comment on the same trap) and would misclassify a retried-and-approved
order as unpaid. This module reads `MlPaymentOps` per payment, exactly
like the Gauss chain.

Two entry points, same underlying rule, because the two call sites need
different shapes:

- `group_accreditation_date_subquery` -- a SQL subquery, one row per
  `group_key`, for a caller that JOINS it into an existing `Query`
  (`ml_sales_query/filters.py`'s date filter and sort key).
- `member_accreditation_dates` -- a bulk Python dict keyed by `order_id`,
  for a caller that already has the group's member ids in memory and
  reduces them itself (`ml_group_metrics/compute.py::_group_date`, which
  works from a prefetched facts dict, not a live Query).

Both filter on the exact same `MlPaymentOps.status.in_(RELEVANT_PAYMENT_STATUSES)`
condition and the exact same `func.max(MlPaymentOps.date_approved)`
aggregate; taking the max of per-order maxima (the second entry point)
is mathematically identical to taking the max directly over every
relevant payment row (the first), because MAX is associative.
"""

from __future__ import annotations

from datetime import datetime
from typing import Any, Dict, Sequence

from sqlalchemy import func
from sqlalchemy.orm import Session

from app.core.config import settings
from app.models.ml_orders_ops import MlOrdersOps
from app.models.ml_payments import MlPaymentOps
from app.services.ml_ventas_desglose.breakdown_service import RELEVANT_PAYMENT_STATUSES


def group_accreditation_date_subquery(db: Session, group_key: Any):
    """One row per group (pack or lone order): `group_key` /
    `accreditation_date` = MAX(date_approved) over the group's relevant
    payments, across ALL its current members.

    `group_key` is the caller's OWN expression (same pattern
    `aggregate_order_metrics(db, listing_query, members_base, group_key)`
    already uses) -- never rebuilt here, so this module never needs to
    import `ml_sales_query.filters` and risk a circular import.

    Inner join to `MlPaymentOps`, deliberately: a group with NO relevant
    payment across any member is simply ABSENT from this result set, which
    is exactly "a sale with no accredited money is in no day" -- a caller
    that INNER JOINs against this subquery drops that group entirely, and
    a caller that LEFT JOINs sees NULL for it.
    """
    q = (
        db.query(
            group_key.label("group_key"),
            func.max(MlPaymentOps.date_approved).label("accreditation_date"),
        )
        .select_from(MlOrdersOps)
        .join(MlPaymentOps, MlPaymentOps.order_id == MlOrdersOps.order_id)
        .filter(MlPaymentOps.status.in_(RELEVANT_PAYMENT_STATUSES))
    )
    if settings.ML_USER_ID:
        q = q.filter(MlOrdersOps.seller_id == int(settings.ML_USER_ID))
    return q.group_by(group_key).subquery()


def member_accreditation_dates(db: Session, order_ids: Sequence[int]) -> Dict[int, datetime]:
    """Bulk `order_id -> MAX(date_approved)` over that order's OWN relevant
    payments, for exactly the requested ids -- ONE query regardless of how
    many orders/groups the caller is resolving (same "read once for the
    whole batch" discipline `ml_group_metrics/compute.py` already applies
    to `_order_facts`/`metrics_state_for_orders`).

    An order with no relevant payment is simply ABSENT from the returned
    dict -- never a `None` value or a fabricated date.
    """
    if not order_ids:
        return {}
    filas = (
        db.query(MlPaymentOps.order_id, func.max(MlPaymentOps.date_approved).label("accreditation_date"))
        .filter(
            MlPaymentOps.order_id.in_(list(order_ids)),
            MlPaymentOps.status.in_(RELEVANT_PAYMENT_STATUSES),
        )
        .group_by(MlPaymentOps.order_id)
        .all()
    )
    return {row.order_id: row.accreditation_date for row in filas if row.accreditation_date is not None}
