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

from dataclasses import dataclass, field, replace
from datetime import datetime
from typing import Any, Dict, Optional, Tuple

from sqlalchemy import String, and_, case, cast, false, func, literal, or_, true
from sqlalchemy.orm import Query, Session, aliased

from app.core.config import settings
from app.models.marca_pm import MarcaPM
from app.models.ml_order_item_costo import MlOrderItemCosto
from app.models.ml_order_metrics import MlOrderMetrics
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
    # PR11.T1 (design D12, spec KPI R9-R11): the four doubtful-case toggle
    # switches. Each, when OFF, excludes the WHOLE GROUP whose COLLAPSED
    # status (across ALL its members, same rule `collapse()` applies) falls
    # in that class -- never a per-order filter. Defaults per spec R11.
    include_unknown: bool = False
    include_in_dispute: bool = False
    include_mixed: bool = True
    include_provisional: bool = True


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

    `pre_switch_listing_query` (K3) is `listing_query` BEFORE the
    doubtful-case switches are applied -- everything else (seller, date,
    status facets, search, product facets) already filtered. It exists so
    a caller that needs to evaluate MULTIPLE switch combinations against
    the SAME otherwise-filtered set (the KPI endpoint's per-toggle
    excluded counts, `excluded_by_toggle_counts`) can do so with one join
    against `_group_switch_subquery` and several conditional aggregates,
    instead of re-running `build_scope` once per combination.
    """

    base: Query
    facet_base: Query
    members_base: Query
    listing_query: Query
    pre_switch_listing_query: Query
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


def _goods_status_for_switch_expr():
    """K0 (product decision, spec KPI R9): the "A revisar" doubtful-case
    classification, ONLY -- a real shipment always outranks the tag, same
    precedence `mode_resolution.resolve_modo_logistico` already applies
    for `modo_logistico`. When there is genuinely no shipment
    (`MlOrdersOps.shipping_id IS NULL`) AND the order carries ML's
    `no_shipping` tag (`has_no_shipping_tag`, `mode_resolution.py`), the
    parcel was handed off in person -- a real sale whose goods status
    simply does not apply, never the same 'unknown' bucket a doubtful,
    un-investigated order falls into. `has_no_shipping_tag` is NULLABLE:
    NULL means "not tagged" and falls through to plain 'unknown',
    unchanged.

    This is DELIBERATELY separate from `_goods_status_expr()` (the value
    shown on the listing/detail badge, unchanged by this fix) -- widening
    the displayed goods_status vocabulary is a future slice's decision,
    not this one's.
    """
    whens = [
        (MlShipmentOps.status == shipping_status, goods_status)
        for shipping_status, goods_status in GOODS_STATUS_BY_SHIPPING_STATUS.items()
    ]
    return case(
        *whens,
        (
            and_(MlOrdersOps.shipping_id.is_(None), MlOrdersOps.has_no_shipping_tag.is_(True)),
            "no_shipping",
        ),
        else_="unknown",
    )


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


def _group_switch_subquery(db: Session, op_status_expr: Any):
    """PR11.T1/T2 (design D12 Mixta resolution): one row per GROUP, computed
    over ALL of a group's members (seller-scoped only, like `members_base`
    -- a switch must agree with what the group's members actually collapse
    to when rendered, not with a date-scoped slice of them). Mirrors what
    `collapse()` (design D12/PR9) does for a Python list, in SQL:

    - `op_distinct`/`op_single`, `goods_distinct`/`goods_single`: a distinct
      count of 0 or 1 means every present member agrees (single value, or
      'unknown' collapse when none are present -- unreachable for a real
      group but mirrors `collapse()`'s empty-list branch); >1 means 'mixed'.
    - `any_in_dispute`: true if ANY member's operation_status is
      'in_dispute' -- En disputa is not a collapse rule, just an existence
      check (design D12).
    - `any_provisional`: true if ANY member's stored `gauss_status` is
      'provisional' -- Provisorio (design D12), via an outer join so a
      member with no metrics row yet contributes `NULL`, never a false
      positive.

    `modo_logistico` is deliberately NOT included here (PR11.T3): it is a
    logistics attribute (design D12), not a status axis, and must never
    drive the Mixta switch.

    The goods axis always uses `_goods_status_for_switch_expr` (K0), NOT
    whatever `goods_status_expr` a caller built for display purposes --
    the switch classification and the displayed badge are deliberately
    allowed to diverge (see that function's docstring).
    """
    goods_switch_expr = _goods_status_for_switch_expr()
    group_key = _group_key_expr()
    q = db.query(
        group_key.label("group_key"),
        func.count(func.distinct(op_status_expr)).label("op_distinct"),
        func.min(op_status_expr).label("op_single"),
        func.count(func.distinct(goods_switch_expr)).label("goods_distinct"),
        func.min(goods_switch_expr).label("goods_single"),
        func.max(case((op_status_expr == "in_dispute", 1), else_=0)).label("any_in_dispute"),
        func.max(case((MlOrderMetrics.gauss_status == "provisional", 1), else_=0)).label("any_provisional"),
    ).outerjoin(MlShipmentOps, MlShipmentOps.shipment_id == MlOrdersOps.shipping_id)
    q = q.outerjoin(MlOrderMetrics, MlOrderMetrics.order_id == MlOrdersOps.order_id)
    if settings.ML_USER_ID:
        q = q.filter(MlOrdersOps.seller_id == int(settings.ML_USER_ID))
    return q.group_by(group_key).subquery()


def _switch_flags(switches: Any) -> "tuple[Any, Any, Any, Any]":
    """The four doubtful-case boolean expressions over one row of
    `_group_switch_subquery`'s result (design D12, spec KPI R9).

    K4 fix: `is_unknown` is derived from an EXPLICIT "this axis collapsed
    to EXACTLY 0 or 1 distinct value, and that value is 'unknown'" check
    -- mirroring `collapse()`'s real semantics -- rather than from
    `MIN()` happening to land on 'unknown' among a genuinely mixed
    (`distinct > 1`) set. The old `op_single == "unknown"` check (with no
    `distinct` guard) only ever worked because 'unknown' sorts after every
    other status name in today's vocabulary, so `MIN()` never picked it
    out of a mixed set BY COINCIDENCE -- a new status name sorting after
    'unknown' would have silently flipped that coincidence and
    double-classified a genuinely mixed group as also 'unknown'. A mixed
    group is caught by `is_mixed` alone, never by `is_unknown` too.
    """
    op_collapsed_unknown = (switches.c.op_distinct == 0) | (
        (switches.c.op_distinct == 1) & (switches.c.op_single == "unknown")
    )
    goods_collapsed_unknown = (switches.c.goods_distinct == 0) | (
        (switches.c.goods_distinct == 1) & (switches.c.goods_single == "unknown")
    )
    is_unknown = op_collapsed_unknown | goods_collapsed_unknown
    is_mixed = (switches.c.op_distinct > 1) | (switches.c.goods_distinct > 1)
    is_in_dispute = switches.c.any_in_dispute == 1
    is_provisional = switches.c.any_provisional == 1
    return is_unknown, is_mixed, is_in_dispute, is_provisional


def effective_switches(f: SalesFilter) -> SalesFilter:
    """K2 (design D12 "explicit facet selection overrides its switch",
    spec KPI R9-R11): a user who explicitly filters `operation_status` to
    'unknown' or 'in_dispute', or `goods_status` to 'unknown', must see
    those rows even while the corresponding toggle is OFF -- an explicit
    per-order facet choice is a stronger signal than the default-hiding
    switch, and the two must never silently fight (an operator clicking
    "En disputa" while the switch defaults OFF must not land on an empty
    table with no explanation).

    Returns a NEW `SalesFilter` with the overridden switches applied; the
    caller's `f` is never mutated (frozen dataclass). Both `build_scope`
    (so the listing and the KPI aggregation stay in parity, spec R10) and
    the router's `effective_switches` response field (design D12
    "response echoes effective switches") MUST go through this one
    function, never re-derive the override independently.
    """
    include_unknown = f.include_unknown or f.operation_status == "unknown" or f.goods_status == "unknown"
    include_in_dispute = f.include_in_dispute or f.operation_status == "in_dispute"
    return replace(f, include_unknown=include_unknown, include_in_dispute=include_in_dispute)


def _apply_switches(query: Query, db: Session, f: SalesFilter, op_status_expr: Any) -> Query:
    """PR11.T2: joins `query` against the group-switch aggregate and filters
    out any group excluded by a currently-OFF toggle (spec KPI R9-R11). All
    four switches ON is a no-op join elided entirely (the common/default
    path touches nothing new).

    `f` is expected to already be the EFFECTIVE filter (`effective_switches`
    applied by the caller, K2) -- this function does not re-apply the
    facet-override rule itself.
    """
    if f.include_unknown and f.include_in_dispute and f.include_mixed and f.include_provisional:
        return query

    switches = _group_switch_subquery(db, op_status_expr)
    group_key = _group_key_expr()
    is_unknown, is_mixed, is_in_dispute, is_provisional = _switch_flags(switches)

    query = query.join(switches, switches.c.group_key == group_key)
    if not f.include_unknown:
        query = query.filter(~is_unknown)
    if not f.include_mixed:
        query = query.filter(~is_mixed)
    if not f.include_in_dispute:
        query = query.filter(~is_in_dispute)
    if not f.include_provisional:
        query = query.filter(~is_provisional)
    return query


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

    Also applies the four doubtful-case toggles (`_apply_switches`, spec
    KPI R9-R11) to `listing_query`/`facet_base`, through `effective_switches`
    (K2: an explicit `operation_status`/`goods_status` facet selection
    overrides its own switch) -- never the raw, unadjusted `f`.
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

    pre_switch_listing_query = listing_query

    # PR11.T2 (design D12, spec KPI R9-R11): the four doubtful-case toggle
    # switches apply to BOTH the listing and the facet/KPI base, same
    # contract as the search and product facets above -- table and KPI
    # strip must always reflect the exact same filtered set (spec R10).
    # K2: an explicit facet selection overrides its own switch -- always go
    # through `effective_switches`, never the raw `f`, so the listing and
    # the KPI aggregation (which independently calls `build_scope` with the
    # same `f`) apply the identical override (spec R10 parity).
    effective_f = effective_switches(f)
    listing_query = _apply_switches(listing_query, db, effective_f, op_status_expr)
    facet_base = _apply_switches(facet_base, db, effective_f, op_status_expr)

    return SalesScope(
        base=base,
        facet_base=facet_base,
        members_base=members_base,
        listing_query=listing_query,
        pre_switch_listing_query=pre_switch_listing_query,
        op_status_expr=op_status_expr,
        goods_status_expr=goods_status_expr,
        group_key=group_key,
    )


def excluded_by_toggle_counts(db: Session, f: SalesFilter) -> Dict[str, int]:
    """K3 (spec KPI R13): for each toggle, how many additional GROUPS
    would be included if ONLY that toggle were flipped ON, holding every
    other active filter (including the other three toggles, and any K2
    facet override) constant. `0` for a toggle that is already effectively
    ON -- nothing of its class is being excluded by it.

    Computed in ONE aggregate query over `pre_switch_listing_query`
    (everything except the switches already filtered) joined ONCE against
    `_group_switch_subquery`, using five `COUNT(DISTINCT CASE WHEN ...)`
    expressions (current + one per toggle) -- never a `build_scope`
    re-run per toggle (was up to four extra full scope queries).
    """
    scope = build_scope(db, f)
    effective_f = effective_switches(f)
    switches = _group_switch_subquery(db, scope.op_status_expr)
    group_key = scope.group_key
    is_unknown, is_mixed, is_in_dispute, is_provisional = _switch_flags(switches)

    def _pass_condition(unknown_on: bool, mixed_on: bool, dispute_on: bool, provisional_on: bool) -> Any:
        conditions = []
        if not unknown_on:
            conditions.append(~is_unknown)
        if not mixed_on:
            conditions.append(~is_mixed)
        if not dispute_on:
            conditions.append(~is_in_dispute)
        if not provisional_on:
            conditions.append(~is_provisional)
        return and_(*conditions) if conditions else true()

    base_state = (
        effective_f.include_unknown,
        effective_f.include_mixed,
        effective_f.include_in_dispute,
        effective_f.include_provisional,
    )

    def _count_label(state: "tuple[bool, bool, bool, bool]", label: str) -> Any:
        condition = _pass_condition(*state)
        return func.count(func.distinct(case((condition, group_key)))).label(label)

    row = (
        scope.pre_switch_listing_query.join(switches, switches.c.group_key == group_key)
        .with_entities(
            _count_label(base_state, "current"),
            _count_label((True, base_state[1], base_state[2], base_state[3]), "unknown_on"),
            _count_label((base_state[0], True, base_state[2], base_state[3]), "mixed_on"),
            _count_label((base_state[0], base_state[1], True, base_state[3]), "dispute_on"),
            _count_label((base_state[0], base_state[1], base_state[2], True), "provisional_on"),
        )
        .one()
    )

    def _excluded(currently_on: bool, with_flip: int) -> int:
        if currently_on:
            return 0
        return with_flip - row.current

    return {
        "a_revisar": _excluded(effective_f.include_unknown, row.unknown_on),
        "en_disputa": _excluded(effective_f.include_in_dispute, row.dispute_on),
        "mixta": _excluded(effective_f.include_mixed, row.mixed_on),
        "provisorio": _excluded(effective_f.include_provisional, row.provisional_on),
    }
