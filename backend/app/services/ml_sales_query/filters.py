"""Shared query layer: `SalesFilter` + `build_scope` (design D12).

PR9.T1/T2: PURE REFACTOR of the query-building logic that used to live
inline in `ml_ventas_ops.py::listar_ventas` -- the order-level status
derivation (`_operation_status_expr`/`_goods_status_expr`), the group key
expression (`_group_key_expr`) and the group-level collapse rule
(`_collapse`), all moved verbatim. `build_scope` must reproduce the EXACT
SAME rows, statuses and grouping the old inline logic produced -- proven by
`tests/services/ml_sales_query/test_filters_build_scope.py` (characterization
test, PR9.T1) and by the full existing
`tests/integration/test_ml_ventas_ops_sales_router.py` suite staying green
after the router was switched to delegate here.

`SalesFilter` carries only what this slice reads. The doubtful-case
toggles and the product-level facets (`marcas`, `subcategorias`, `pms`)
are added by the PRs that apply them, so nothing here is a field no code
uses.
"""

from __future__ import annotations

from dataclasses import dataclass
from datetime import datetime
from typing import Any, Optional, Tuple

from sqlalchemy import String, case, cast, literal
from sqlalchemy.orm import Query, Session

from app.core.config import settings
from app.models.ml_orders_ops import MlOperationLink, MlOrdersOps, MlShipmentOps
from app.models.rma_claim_ml import RmaClaimML
from app.services.ml_orders_ingestion.operation_status import (
    GOODS_STATUS_BY_SHIPPING_STATUS,
    PAID_ORDER_STATUSES,
    SETTLED_CLAIM_STATUSES,
)
from app.services.ml_sales_query.search import apply_search


@dataclass(frozen=True)
class SalesFilter:
    """Design D12 interface: every filter this slice applies, and nothing
    else. A later PR that adds a filter adds its field here together with
    the code that reads it."""

    date_range: Optional[Tuple[datetime, datetime]] = None
    operation_status: Optional[str] = None
    goods_status: Optional[str] = None
    q: Optional[str] = None


@dataclass
class SalesScope:
    """What `build_scope` hands back: enough query-building blocks for a
    caller to page/group/facet the result, without re-deriving any of the
    status/grouping logic itself.

    `base` is the seller+date-scoped query with NO status/search filter
    applied. `facet_base` is `base` PLUS the search: the facet counts must
    be narrowed by the OTHER active status axis, but they must ALSO obey
    the search, or the "Todas" chip reports rows the table does not show
    (SEARCH R26). `members_base` is scoped ONLY to the seller -- NOT the date
    range either -- because a filter (status OR month) selects which
    GROUPS to show, never which of their orders to hide: a pack that
    straddles a month boundary must still come back with every member,
    including the one outside the requested month (same contract the old
    inline `members_base` had). `listing_query` is `base` PLUS the
    operation/goods status filters and the search filter, which is what
    selects which GROUPS appear on the page.
    """

    base: Query
    facet_base: Query
    members_base: Query
    listing_query: Query
    op_status_expr: Any
    goods_status_expr: Any
    group_key: Any


def _open_claim_exists_subquery(db: Session):
    """Moved verbatim from `ml_ventas_ops.py::_open_claim_exists_subquery`."""
    return (
        db.query(MlOperationLink.id)
        .join(RmaClaimML, RmaClaimML.id == MlOperationLink.entity_id)
        .filter(
            MlOperationLink.entity_type == "claim",
            MlOperationLink.order_id == MlOrdersOps.order_id,
            RmaClaimML.status.isnot(None),
            ~RmaClaimML.status.in_(tuple(SETTLED_CLAIM_STATUSES)),
        )
        .exists()
    )


def _operation_status_expr(open_claim_exists):
    """Moved verbatim from `ml_ventas_ops.py::_operation_status_expr`."""
    return case(
        (
            MlOrdersOps.status == "cancelled",
            case(
                (MlOrdersOps.covered_by_marketplace.is_(True), "cancelled_ml_covered"),
                else_="cancelled",
            ),
        ),
        (MlOrdersOps.payment_status == "in_mediation", "in_dispute"),
        (open_claim_exists, "in_dispute"),
        (MlShipmentOps.status == "delivered", "delivered"),
        (MlOrdersOps.status.in_(tuple(PAID_ORDER_STATUSES)), "paid"),
        else_="unknown",
    )


def _goods_status_expr():
    """Moved verbatim from `ml_ventas_ops.py::_goods_status_expr`."""
    whens = [
        (MlShipmentOps.status == shipping_status, goods_status)
        for shipping_status, goods_status in GOODS_STATUS_BY_SHIPPING_STATUS.items()
    ]
    return case(*whens, else_="unknown")


def _group_key_expr():
    """Moved verbatim from `ml_ventas_ops.py::_group_key_expr`."""
    return case(
        (MlOrdersOps.pack_id.isnot(None), literal("p:") + cast(MlOrdersOps.pack_id, String)),
        else_=literal("o:") + cast(MlOrdersOps.order_id, String),
    )


def collapse(values: "list[Optional[str]]") -> str:
    """Moved verbatim from `ml_ventas_ops.py::_collapse` (renamed, no
    leading underscore, now a shared function)."""
    distinct = {v for v in values if v is not None}
    if not distinct:
        return "unknown"
    if len(distinct) == 1:
        return distinct.pop()
    return "mixed"


def build_scope(db: Session, f: SalesFilter) -> SalesScope:
    """Order-level base query + group-level building blocks, scoped to the
    configured seller (same as the old inline logic), the filter's date
    range, its operation/goods status facets and its free-text search.

    `apply_switches` semantics (the four doubtful-case toggles, KPI R9-R11)
    are NOT applied yet -- that is PR11's `SalesFilter.include_*` wiring.
    """
    open_claim_exists = _open_claim_exists_subquery(db)
    op_status_expr = _operation_status_expr(open_claim_exists)
    goods_status_expr = _goods_status_expr()
    group_key = _group_key_expr()

    base = db.query(MlOrdersOps, MlShipmentOps).outerjoin(
        MlShipmentOps, MlShipmentOps.shipment_id == MlOrdersOps.shipping_id
    )
    if settings.ML_USER_ID:
        base = base.filter(MlOrdersOps.seller_id == int(settings.ML_USER_ID))
    if f.date_range is not None:
        base = base.filter(MlOrdersOps.date_created >= f.date_range[0], MlOrdersOps.date_created < f.date_range[1])

    # Every order of a group on the page, regardless of the filters that
    # selected that group -- scoped to the seller only (see `SalesScope`
    # docstring: NOT the date range, NOT the status filters).
    members_base = db.query(MlOrdersOps, MlShipmentOps).outerjoin(
        MlShipmentOps, MlShipmentOps.shipment_id == MlOrdersOps.shipping_id
    )
    if settings.ML_USER_ID:
        members_base = members_base.filter(MlOrdersOps.seller_id == int(settings.ML_USER_ID))

    listing_query = base
    if f.operation_status is not None:
        listing_query = listing_query.filter(op_status_expr == f.operation_status)
    if f.goods_status is not None:
        listing_query = listing_query.filter(goods_status_expr == f.goods_status)
    listing_query = apply_search(listing_query, db, f.q)

    return SalesScope(
        base=base,
        facet_base=apply_search(base, db, f.q),
        members_base=members_base,
        listing_query=listing_query,
        op_status_expr=op_status_expr,
        goods_status_expr=goods_status_expr,
        group_key=group_key,
    )
