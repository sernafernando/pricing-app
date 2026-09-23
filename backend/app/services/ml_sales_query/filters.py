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

`SalesFilter` also carries the D12a product-level facet fields
(`marcas`, `subcategorias`, `pms`), applied by `build_scope` through
`_product_facet_exists`: ONE item of the sale must satisfy EVERY active
facet, and a match returns the whole group (spec PFILT R38).
"""

from __future__ import annotations

from dataclasses import dataclass, field
from datetime import datetime
from typing import Any, Optional, Tuple

from sqlalchemy import String, and_, case, cast, false, func, literal, or_
from sqlalchemy.orm import Query, Session, aliased

from app.core.config import settings
from app.models.marca_pm import MarcaPM
from app.models.ml_order_item_costo import MlOrderItemCosto
from app.models.ml_orders_ops import MlOperationLink, MlOrdersOps, MlShipmentOps
from app.models.producto import ProductoERP
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
    # D12a product-level facets (spec PFILT R35), applied by `build_scope`
    # through `_product_facet_exists`.
    marcas: Tuple[str, ...] = field(default_factory=tuple)
    subcategorias: Tuple[int, ...] = field(default_factory=tuple)
    pms: Tuple[int, ...] = field(default_factory=tuple)


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


def _resolve_pm_pairs(db: Session, pms: Tuple[int, ...]) -> "list[tuple[str, str]]":
    """Resolves the marca+categoria pairs assigned to the selected PM
    users, the same rule `productos_listing.py` applies in its own `pms`
    branch. This is a THIRD copy of that query, not a reuse: extracting a
    shared helper touches the products listing, which this slice does not
    open. If the PM pair rule changes, this must change with it."""
    pares_pm = db.query(MarcaPM.marca, MarcaPM.categoria).filter(MarcaPM.usuario_id.in_(pms)).all()
    return [(m.upper(), c.upper()) for m, c in pares_pm]


def _product_facet_exists(db: Session, f: SalesFilter, group_key: Any) -> Optional[Any]:
    """Design D12a / spec PFILT R35-R39: a SINGLE correlated `EXISTS` over
    every order-item belonging to the SAME GROUP (pack or lone order) as
    the outer row, carrying EVERY active facet condition AND-ed together
    (R38 conjunction -- never one EXISTS per facet OR'd, which would let
    different items satisfy different facets).

    Correlates by `group_key` (not `order_id`) so a pack matches when ANY
    ONE of its member orders' items satisfies every facet, and the whole
    group comes back (pack semantics). An order-item with no frozen cost
    row (`ml_order_item_costos`) is excluded by the INNER joins below and
    can never contribute a match on its own (R39).

    Returns `None` when no product-level facet is active (caller must not
    apply a no-op filter).
    """
    if not (f.marcas or f.subcategorias or f.pms):
        return None

    order_alias = aliased(MlOrdersOps)
    alias_group_key = case(
        (order_alias.pack_id.isnot(None), literal("p:") + cast(order_alias.pack_id, String)),
        else_=literal("o:") + cast(order_alias.order_id, String),
    )

    conditions = [alias_group_key == group_key]
    if settings.ML_USER_ID:
        conditions.append(order_alias.seller_id == int(settings.ML_USER_ID))

    if f.marcas:
        marcas_upper = [m.upper() for m in f.marcas]
        conditions.append(func.upper(ProductoERP.marca).in_(marcas_upper))

    if f.subcategorias:
        conditions.append(ProductoERP.subcategoria_id.in_(f.subcategorias))

    if f.pms:
        pares_pm = _resolve_pm_pairs(db, f.pms)
        if not pares_pm:
            # PFILT binding decision: a PM with NO assigned pairs matches
            # NOTHING -- never every sale.
            conditions.append(false())
        else:
            conditions.append(
                or_(
                    *(
                        and_(func.upper(ProductoERP.marca) == marca, func.upper(ProductoERP.categoria) == categoria)
                        for marca, categoria in pares_pm
                    )
                )
            )

    return (
        db.query(MlOrderItemCosto.id)
        .join(order_alias, order_alias.order_id == MlOrderItemCosto.order_id)
        .join(ProductoERP, ProductoERP.item_id == MlOrderItemCosto.producto_item_id)
        .filter(*conditions)
        .exists()
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

    # The product facets narrow BOTH the page and the chip counts: a chip
    # reporting the whole period while the table shows one row contradicts
    # the table under it (same contract as the search, SEARCH R26).
    facet_base = apply_search(base, db, f.q)
    facet_exists = _product_facet_exists(db, f, group_key)
    if facet_exists is not None:
        listing_query = listing_query.filter(facet_exists)
        facet_base = facet_base.filter(facet_exists)

    return SalesScope(
        base=base,
        facet_base=facet_base,
        members_base=members_base,
        listing_query=listing_query,
        op_status_expr=op_status_expr,
        goods_status_expr=goods_status_expr,
        group_key=group_key,
    )
