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
from app.models.mercadolibre_item_publicado import MercadoLibreItemPublicado
from app.models.ml_order_item_costo import MlOrderItemCosto
from app.models.ml_order_metrics import MlOrderMetrics, MlOrderMetricsDirty
from app.models.ml_orders_ops import MlOperationLink, MlOrderItemOps, MlOrdersOps, MlShipmentOps
from app.models.producto import ProductoERP
from app.models.rma_claim_ml import RmaClaimML
from app.services.ml_orders_ingestion.operation_status import (
    GOODS_STATUS_BY_SHIPPING_STATUS,
    PAID_ORDER_STATUSES,
    SETTLED_CLAIM_STATUSES,
)
from app.services.ml_sales_query.accreditation import group_accreditation_date_subquery
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
    # ODD `ventas-ml-ui-pendiente` T8: "Canceladas" switch. ON (default)
    # keeps today's numbers; OFF hides the groups whose COLLAPSED operation
    # status is plain `cancelled`. `cancelled_ml_covered` is NOT hidden: the
    # money arrived (Buyer Protection), it is a sale commercially.
    include_cancelled: bool = True
    # ODD `ventas-ml-ui-pendiente` T5: "Solo con alertas". Keeps the groups
    # where ANY member order's alert level (`ml_ventas_ops._alert_level`) is
    # not `ok`. A scope filter like the product facets, not a switch: it
    # applies to the listing, the facets and the KPI alike.
    only_alerts: bool = False
    # ODD `metricas-ml-tablero` T1: official stores (`mlp_official_store_id`
    # of the item's MLA) plus `NO_STORE` for an MLA with no store. A GROUP
    # filter like the product facets: applied by `build_scope` through
    # `_store_exists`, to the listing, the facets and the KPI alike.
    stores: Tuple[str, ...] = field(default_factory=tuple)


# The `stores` sentinel for "the MLA has no official store": no publication
# row at all, or one whose `mlp_official_store_id` is NULL. Same literal the
# products export already accepts (`productos_shared.parsear_tiendas_oficiales_mla`).
NO_STORE = "sin_tienda"


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
    # ODD `ventas-ml-dia-por-acreditacion`: the accreditation subquery,
    # ALWAYS handed back so a caller that needs it (the day filter, or the
    # accreditation-based sort) can join or read it -- but only actually
    # LEFT-joined onto `base`/`listing_query` when `accreditation_joined`
    # is True (a date filter was active). `base` is shared by every derived
    # query (key page, total, facets, switches), so joining this
    # unconditionally would tax every one of them even when nothing reads
    # it. A caller that needs the column on a path where it is NOT joined
    # (the accreditation sort with no date filter) must join it itself,
    # exactly once, onto the specific query it is building.
    accreditation_subquery: Any
    accreditation_joined: bool
    # ODD `ventas-ml-ui-pendiente` T5: the listing scope as it would be
    # WITHOUT the `only_alerts` filter itself (every other filter and switch
    # applied) and restricted to groups with an alert -- what the "Solo con
    # alertas (N)" counter counts, so it stays meaningful while the filter is
    # ON (same rule as every facet: never scoped by its own axis).
    alert_groups_query: Any = None
    # ODD `metricas-ml-tablero` T1: `facet_base` WITHOUT the store filter, so
    # the "TIENDA:" chip counts are never scoped by their own axis.
    store_facet_base: Any = None


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


def _store_publication(item_mla: Any):
    """The publication rows of one order item's MLA that carry a store."""
    return and_(
        MercadoLibreItemPublicado.mlp_publicationID == item_mla,
        MercadoLibreItemPublicado.mlp_official_store_id.isnot(None),
    )


def _store_exists(db: Session, f: SalesFilter, group_key: Any) -> Optional[Any]:
    """ODD `metricas-ml-tablero` T1: one correlated `EXISTS` over every
    order item (`ml_order_items_ops`, so an item with no frozen cost still
    counts) of the SAME GROUP as the outer row, true when that item's MLA is
    published in one of `f.stores` -- or, for `NO_STORE`, has no publication
    carrying a store. Correlated by `group_key` exactly like
    `_product_facet_exists`, so a pack matches as a whole.

    The MLA -> store lookup rides `tb_mercadolibre_items_publicados`'
    `mlp_publicationid` index (migration 20261001_ix_mlp_publicationid).

    Returns `None` when no store is selected.
    """
    if not f.stores:
        return None
    store_ids = [int(s) for s in f.stores if s != NO_STORE]
    order_alias = aliased(MlOrdersOps)
    alias_group_key = case(
        (order_alias.pack_id.isnot(None), literal("p:") + cast(order_alias.pack_id, String)),
        else_=literal("o:") + cast(order_alias.order_id, String),
    )
    store_publication = _store_publication(MlOrderItemOps.item_id)
    item_matches = []
    if store_ids:
        item_matches.append(
            db.query(MercadoLibreItemPublicado.mlp_id)
            .filter(store_publication, MercadoLibreItemPublicado.mlp_official_store_id.in_(store_ids))
            .exists()
        )
    if NO_STORE in f.stores:
        item_matches.append(~db.query(MercadoLibreItemPublicado.mlp_id).filter(store_publication).exists())

    conditions = [alias_group_key == group_key, or_(*item_matches)]
    if settings.ML_USER_ID:
        conditions.append(order_alias.seller_id == int(settings.ML_USER_ID))
    return (
        db.query(MlOrderItemOps.id)
        .join(order_alias, order_alias.order_id == MlOrderItemOps.order_id)
        .filter(*conditions)
        .exists()
    )


def _group_store_subquery(db: Session):
    """One row per (group, store bucket) the group touches: the store id as
    text, or `NO_STORE`. Feeds the "TIENDA:" facet counts -- a pack spanning
    two stores counts under both, like a mixed pack in the status facets.
    The bucket rule is `_store_exists`' rule, so a chip's count is what
    clicking it returns."""
    group_key = _group_key_expr()
    bucket = func.coalesce(cast(MercadoLibreItemPublicado.mlp_official_store_id, String), literal(NO_STORE))
    q = (
        db.query(group_key.label("group_key"), bucket.label("store"))
        .join(MlOrderItemOps, MlOrderItemOps.order_id == MlOrdersOps.order_id)
        .outerjoin(MercadoLibreItemPublicado, _store_publication(MlOrderItemOps.item_id))
    )
    if settings.ML_USER_ID:
        q = q.filter(MlOrdersOps.seller_id == int(settings.ML_USER_ID))
    return q.distinct().subquery()


def store_facet_counts(scope: "SalesScope") -> "tuple[Dict[str, int], int]":
    """Groups per store bucket inside the scope every OTHER filter leaves
    standing, and how many groups that scope holds ("Todas")."""
    db = scope.store_facet_base.session
    stores = _group_store_subquery(db)
    rows = (
        scope.store_facet_base.join(stores, stores.c.group_key == scope.group_key)
        .with_entities(stores.c.store, func.count(func.distinct(scope.group_key)))
        .group_by(stores.c.store)
        .all()
    )
    total = scope.store_facet_base.with_entities(func.count(func.distinct(scope.group_key))).scalar() or 0
    return {store: count for store, count in rows}, total


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


def _group_alert_subquery(db: Session, op_status_expr: Any, goods_status_expr: Any):
    """ODD `ventas-ml-ui-pendiente` T5: one row per GROUP with `has_alert`,
    the SQL equivalent of "any member's `ml_ventas_ops._alert_level` is not
    `ok`". A member is clean only when ALL of these hold, which mirrors
    `_alert_level` + `read.metrics_state_for_orders`:

    - no dirty-queue row (a dirty row is `recalculating` or `failed`);
    - a stored metrics row exists (none = `pending`) with `gauss_status` `ok`
      (`provisional` and `unresolved` are alerts);
    - its `neto` is known and its IVA split does not report `False`
      (`NULL` = not judged, same as the Python `is False` check);
    - neither status axis is `unknown` (display axes, as the router sees them).

    If `_alert_level` changes, this must change with it: the router parity
    test `test_ml_ventas_ops_alerts_router.py` compares them row by row.
    """
    group_key = _group_key_expr()
    member_is_clean = and_(
        MlOrderMetricsDirty.order_id.is_(None),
        MlOrderMetrics.order_id.isnot(None),
        MlOrderMetrics.gauss_status == "ok",
        MlOrderMetrics.neto.isnot(None),
        or_(MlOrderMetrics.iva_reconcilia.is_(None), MlOrderMetrics.iva_reconcilia.is_(True)),
        op_status_expr != "unknown",
        goods_status_expr != "unknown",
    )
    q = (
        db.query(
            group_key.label("group_key"),
            func.max(case((member_is_clean, 0), else_=1)).label("has_alert"),
        )
        .outerjoin(MlShipmentOps, MlShipmentOps.shipment_id == MlOrdersOps.shipping_id)
        .outerjoin(MlOrderMetrics, MlOrderMetrics.order_id == MlOrdersOps.order_id)
        .outerjoin(MlOrderMetricsDirty, MlOrderMetricsDirty.order_id == MlOrdersOps.order_id)
    )
    if settings.ML_USER_ID:
        q = q.filter(MlOrdersOps.seller_id == int(settings.ML_USER_ID))
    return q.group_by(group_key).subquery()


def _only_groups_with_alert(query: Query, db: Session, op_status_expr: Any, goods_status_expr: Any) -> Query:
    alerts = _group_alert_subquery(db, op_status_expr, goods_status_expr)
    return query.join(alerts, alerts.c.group_key == _group_key_expr()).filter(alerts.c.has_alert == 1)


def alert_groups_count(scope: "SalesScope") -> int:
    """How many GROUPS with an alert the current scope holds, ignoring the
    `only_alerts` filter itself (see `SalesScope.alert_groups_query`)."""
    return scope.alert_groups_query.with_entities(func.count(func.distinct(scope.group_key))).scalar() or 0


def _switch_flags(switches: Any) -> "tuple[Any, Any, Any, Any, Any]":
    """The five toggle boolean expressions over one row of
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
    # Collapsed like `collapse()`: every member agrees AND it is `cancelled`.
    # A pack mixing a cancelled and a paid order is `mixed`, not cancelled.
    is_cancelled = (switches.c.op_distinct == 1) & (switches.c.op_single == "cancelled")
    return is_unknown, is_mixed, is_in_dispute, is_provisional, is_cancelled


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
    include_cancelled = f.include_cancelled or f.operation_status == "cancelled"
    return replace(
        f,
        include_unknown=include_unknown,
        include_in_dispute=include_in_dispute,
        include_cancelled=include_cancelled,
    )


def _apply_switches(query: Query, db: Session, f: SalesFilter, op_status_expr: Any) -> Query:
    """PR11.T2: joins `query` against the group-switch aggregate and filters
    out any group excluded by a currently-OFF toggle (spec KPI R9-R11). All
    four switches ON is a no-op join elided entirely (the common/default
    path touches nothing new).

    `f` is expected to already be the EFFECTIVE filter (`effective_switches`
    applied by the caller, K2) -- this function does not re-apply the
    facet-override rule itself.
    """
    if f.include_unknown and f.include_in_dispute and f.include_mixed and f.include_provisional and f.include_cancelled:
        return query

    switches = _group_switch_subquery(db, op_status_expr)
    group_key = _group_key_expr()
    is_unknown, is_mixed, is_in_dispute, is_provisional, is_cancelled = _switch_flags(switches)

    query = query.join(switches, switches.c.group_key == group_key)
    if not f.include_unknown:
        query = query.filter(~is_unknown)
    if not f.include_mixed:
        query = query.filter(~is_mixed)
    if not f.include_in_dispute:
        query = query.filter(~is_in_dispute)
    if not f.include_provisional:
        query = query.filter(~is_provisional)
    if not f.include_cancelled:
        query = query.filter(~is_cancelled)
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
    # ODD `ventas-ml-dia-por-acreditacion` (2026-09-30): the day is when the
    # money ACCREDITED, not `date_created` -- see
    # `accreditation.group_accreditation_date_subquery`'s docstring for the
    # full rule. The subquery is built here regardless, but (T4 review
    # finding #2) LEFT-joined onto the shared `base` ONLY when a date range
    # actually filters the page -- `base` feeds every derived query (key
    # page, total, facets, switches), so an unconditional join taxes ALL of
    # them even on the far more common request that neither filters nor
    # sorts by accreditation. A caller that needs the column on the
    # unjoined path (the accreditation-based sort with no date filter,
    # `ml_ventas_ops.py`) joins `accred` itself, once, onto the specific
    # query it is building -- `accreditation_joined` on `SalesScope` tells
    # it whether that join already happened here. An unaccredited order
    # gets `accreditation_date IS NULL` from the LEFT join; the WHERE below
    # only applies when a date range was actually requested, and NULL fails
    # that comparison on both engines -- "a sale with no accredited money is
    # in no day" falls out of the LEFT join + WHERE combination without a
    # separate exclusion rule.
    accred = group_accreditation_date_subquery(db, group_key)
    accreditation_joined = f.date_range is not None
    if accreditation_joined:
        base = base.outerjoin(accred, accred.c.group_key == group_key)
        base = base.filter(
            accred.c.accreditation_date >= f.date_range[0], accred.c.accreditation_date < f.date_range[1]
        )

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
    # The store chips are counted over everything EXCEPT the store filter.
    store_facet_base = facet_base
    store_exists = _store_exists(db, f, group_key)
    if store_exists is not None:
        listing_query = listing_query.filter(store_exists)
        facet_base = facet_base.filter(store_exists)

    # Kept apart so the alert COUNTER can ignore the alert filter itself.
    listing_before_alerts = listing_query
    if f.only_alerts:
        listing_query = _only_groups_with_alert(listing_query, db, op_status_expr, goods_status_expr)
        facet_base = _only_groups_with_alert(facet_base, db, op_status_expr, goods_status_expr)
        store_facet_base = _only_groups_with_alert(store_facet_base, db, op_status_expr, goods_status_expr)

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
    store_facet_base = _apply_switches(store_facet_base, db, effective_f, op_status_expr)
    alert_groups_query = _only_groups_with_alert(
        _apply_switches(listing_before_alerts, db, effective_f, op_status_expr), db, op_status_expr, goods_status_expr
    )

    return SalesScope(
        base=base,
        facet_base=facet_base,
        members_base=members_base,
        listing_query=listing_query,
        pre_switch_listing_query=pre_switch_listing_query,
        op_status_expr=op_status_expr,
        goods_status_expr=goods_status_expr,
        group_key=group_key,
        accreditation_subquery=accred,
        accreditation_joined=accreditation_joined,
        alert_groups_query=alert_groups_query,
        store_facet_base=store_facet_base,
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
    is_unknown, is_mixed, is_in_dispute, is_provisional, is_cancelled = _switch_flags(switches)

    def _pass_condition(
        unknown_on: bool, mixed_on: bool, dispute_on: bool, provisional_on: bool, cancelled_on: bool
    ) -> Any:
        conditions = []
        if not unknown_on:
            conditions.append(~is_unknown)
        if not mixed_on:
            conditions.append(~is_mixed)
        if not dispute_on:
            conditions.append(~is_in_dispute)
        if not provisional_on:
            conditions.append(~is_provisional)
        if not cancelled_on:
            conditions.append(~is_cancelled)
        return and_(*conditions) if conditions else true()

    base_state = (
        effective_f.include_unknown,
        effective_f.include_mixed,
        effective_f.include_in_dispute,
        effective_f.include_provisional,
        effective_f.include_cancelled,
    )

    def _count_label(state: "tuple[bool, bool, bool, bool, bool]", label: str) -> Any:
        condition = _pass_condition(*state)
        return func.count(func.distinct(case((condition, group_key)))).label(label)

    row = (
        scope.pre_switch_listing_query.join(switches, switches.c.group_key == group_key)
        .with_entities(
            _count_label(base_state, "current"),
            _count_label((True, *base_state[1:]), "unknown_on"),
            _count_label((base_state[0], True, *base_state[2:]), "mixed_on"),
            _count_label((*base_state[:2], True, *base_state[3:]), "dispute_on"),
            _count_label((*base_state[:3], True, base_state[4]), "provisional_on"),
            _count_label((*base_state[:4], True), "cancelled_on"),
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
        "canceladas": _excluded(effective_f.include_cancelled, row.cancelled_on),
    }
