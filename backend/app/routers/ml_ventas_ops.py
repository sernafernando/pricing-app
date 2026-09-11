"""Router: ML operations sale-centric view (slice 4 of
ml-ventas-fuente-de-verdad).

Design D4: one storage layer, two read surfaces. This router is the
sale-centric one -- order + items + shipment + linked claim + linked
questions/messages, resolved through `ml_operation_links`. The existing
`ml_bot` router (bot-centric, keyed on question/message) is UNCHANGED by
this module; see `tests/integration/test_ml_ventas_ops_router.py` for the
regression proof.

Gated by:
- `ml_ops.ver` permission (no permission -> 403), checked FIRST.
- `ML_ORDERS_OPS_ENABLED` (flag OFF -> 503, spec: inert by default), checked
  only once permission is confirmed.

Permission is intentionally checked before the flag (same precedent/
rationale as `pxq.py`'s `_SYNC_STATUS_TO_HTTP` comment): a user WITHOUT
permission must always get 403 regardless of flag state, or the response
would leak whether the feature exists/is enabled to someone who cannot use
it either way. 503 then unambiguously means "you can use this, but it's
switched off right now" for a user who already cleared the permission gate.
"""

from __future__ import annotations

import calendar
from datetime import date, datetime, time, timedelta, timezone
from zoneinfo import ZoneInfo
from typing import Dict, List, Optional, Tuple

from fastapi import APIRouter, BackgroundTasks, Depends, HTTPException, Query, status
from pydantic import BaseModel, ConfigDict, Field
from sqlalchemy import String, case, cast, func, literal
from sqlalchemy.orm import Session

from app.api.deps import get_current_user
from app.core.config import settings
from app.core.constants import BUSINESS_TIMEZONE
from app.core.database import get_db
from app.models.ml_bot_message import MlBotMessage
from app.models.ml_bot_question import MlBotQuestion
from app.models.ml_orders_ops import (
    COST_SYNC_FIELD_PREFIX,
    COST_SYNC_KIND,
    COST_SYNC_SENTINEL_ORDER_ID,
    UNENUMERABLE_KIND,
    MlOperationLink,
    MlOpsDivergence,
    MlOrderItemOps,
    MlOrdersOps,
    MlShipmentOps,
)
from app.models.rma_claim_ml import RmaClaimML
from app.models.usuario import Usuario
from app.services.ml_orders_ingestion.activity_receiver_service import drain_activity
from app.services.ml_orders_ingestion.mode_resolution import resolve_modo_logistico
from app.services.ml_orders_ingestion.operation_status import (
    GOODS_STATUS_BY_SHIPPING_STATUS,
    GOODS_STATUSES,
    OPERATION_STATUSES,
    PAID_ORDER_STATUSES,
    SETTLED_CLAIM_STATUSES,
)
from app.services.ml_ventas_desglose.breakdown_service import compute_breakdown, compute_neto_by_order_ids
from app.services.permisos_service import PermisosService

DIVERGENCE_KINDS = (
    "missing_in_gbp",
    "missing_in_ml",
    "field_mismatch",
    "out_of_window_update",
    UNENUMERABLE_KIND,
    "unknown",
)
DIVERGENCE_STATES = ("open", "acknowledged", "resolved", "ignored")
# `window_not_enumerable` uses `order_id=0` as a sentinel (no single order
# for an unenumerable leaf, see `sweep_service.record_unenumerable_window`)
# -- MUST NOT render as an order id (mandatory debt from slice 3).
_UNENUMERABLE_SENTINEL_ORDER_ID = 0

router = APIRouter(prefix="/ml-ventas-ops", tags=["ML Ventas Ops"])


def require_permission(permission: str):
    """Dependency for a required permission code -- same pattern as
    `document_templates.py`/`alertas.py`, reused rather than reinvented."""

    def _check_permission(
        current_user: Usuario = Depends(get_current_user),
        db: Session = Depends(get_db),
    ) -> Usuario:
        permisos_service = PermisosService(db)
        if not permisos_service.tiene_permiso(current_user, permission):
            raise HTTPException(
                status_code=status.HTTP_403_FORBIDDEN,
                detail=f"No tienes permiso: {permission}",
            )
        return current_user

    return _check_permission


def _require_flag_enabled() -> None:
    if not settings.ML_ORDERS_OPS_ENABLED:
        raise HTTPException(
            status_code=status.HTTP_503_SERVICE_UNAVAILABLE,
            detail="ML operations source-of-truth is disabled (ML_ORDERS_OPS_ENABLED=false)",
        )


# ── Schemas ──────────────────────────────────────────────────────


class OrderOpsSummary(BaseModel):
    order_id: int
    pack_id: Optional[int] = None
    status: Optional[str] = None
    status_detail: Optional[str] = None
    buyer_id: Optional[int] = None
    buyer_nickname: Optional[str] = None
    seller_id: int
    total_amount: Optional[float] = None
    paid_amount: Optional[float] = None
    currency_id: Optional[str] = None

    model_config = ConfigDict(from_attributes=True)


class OrderItemOpsSummary(BaseModel):
    item_id: str
    variation_id: Optional[int] = None
    seller_sku: Optional[str] = None
    title: Optional[str] = None
    quantity: Optional[int] = None
    unit_price: Optional[float] = None

    model_config = ConfigDict(from_attributes=True)


class ShipmentOpsSummary(BaseModel):
    shipment_id: int
    status: Optional[str] = None
    substatus: Optional[str] = None
    tracking_number: Optional[str] = None

    model_config = ConfigDict(from_attributes=True)


class ClaimSummary(BaseModel):
    claim_id: int
    claim_type: Optional[str] = None
    status: Optional[str] = None
    reason_category: Optional[str] = None

    model_config = ConfigDict(from_attributes=True)


class QuestionSummary(BaseModel):
    ml_question_id: int
    item_id: str
    question_text: str
    status: str

    model_config = ConfigDict(from_attributes=True)


class MessageSummary(BaseModel):
    ml_message_id: str
    text: str
    status: str

    model_config = ConfigDict(from_attributes=True)


class BreakdownLineSummary(BaseModel):
    """One line of the cost breakdown.

    `origen` says WHERE the number came from, and it is not one value any
    more. `"api"` means ML's own payment/billing data, straight through
    with nothing computed here (corte 6 of ml-ventas-desglose-costos).
    `"propio"` means OUR preparation tables -- today the real Flex cost,
    resolved from the shipping label's `costo_override` or the logistics
    provider's cordon tariff, which ML never tells us.

    The distinction is the point: an operator reading a Flex sale has to
    be able to tell the cost we pay from the charge ML bills."""

    concepto: str
    monto: float
    origen: str = "api"


class OperationBreakdownSummary(BaseModel):
    """The sale's cost breakdown. `incompleto=True` with a populated
    `incomplete_reasons` means data is missing -- `neto` is never a
    fabricated number in that case (it is `None` when payments have not
    even synced)."""

    lines: List[BreakdownLineSummary]
    neto: Optional[float] = None
    incompleto: bool
    incomplete_reasons: List[str]

    @classmethod
    def from_domain(cls, breakdown) -> "OperationBreakdownSummary":
        return cls(
            lines=[
                BreakdownLineSummary(concepto=line.concepto, monto=float(line.monto), origen=line.origen)
                for line in breakdown.lines
            ],
            neto=float(breakdown.neto) if breakdown.neto is not None else None,
            incompleto=breakdown.incompleto,
            incomplete_reasons=list(breakdown.incomplete_reasons),
        )


class SaleCentricOperation(BaseModel):
    order: OrderOpsSummary
    items: List[OrderItemOpsSummary]
    shipment: Optional[ShipmentOpsSummary] = None
    claim: Optional[ClaimSummary] = None
    questions: List[QuestionSummary]
    messages: List[MessageSummary]
    breakdown: OperationBreakdownSummary

    model_config = ConfigDict(from_attributes=True)


class DivergenceSummary(BaseModel):
    """A single `ml_ops_divergence` row. `order_id` is `None` for
    `window_not_enumerable` rows (see `_UNENUMERABLE_SENTINEL_ORDER_ID`);
    `window_from`/`window_to` carry that kind's leaf bounds instead."""

    id: int
    order_id: Optional[int] = None
    kind: str
    field: Optional[str] = None
    ml_value: Optional[str] = None
    gbp_value: Optional[str] = None
    window_from: Optional[str] = None
    window_to: Optional[str] = None
    state: str
    assigned_to_id: Optional[int] = None
    note: Optional[str] = None
    detected_at: datetime = Field(
        description=(
            "When this divergence was FIRST detected, or first detected since it last "
            "reopened -- not when it was last seen. Detection skips a divergence whose "
            "values have not changed, so this timestamp does not advance while the same "
            "difference persists. `out_of_window_update` and `window_not_enumerable` "
            "come from a different write path and do mean last seen."
        )
    )
    updated_at: datetime

    model_config = ConfigDict(from_attributes=True)

    @classmethod
    def from_row(cls, row: MlOpsDivergence) -> "DivergenceSummary":
        is_unenumerable = row.kind == UNENUMERABLE_KIND and row.order_id == _UNENUMERABLE_SENTINEL_ORDER_ID
        # Cost-sync give-up counters share the `order_id=0` sentinel but
        # not the `window_not_enumerable` kind, so they need their own
        # test: without it they render as ML order 0, an order that does
        # not exist. Their `field` (`cost_sync:<shipment_id>`) and
        # `ml_value` (the attempt count) ARE meaningful, so only the
        # sentinel order id is masked.
        is_cost_sync = (
            row.kind == COST_SYNC_KIND
            and row.order_id == COST_SYNC_SENTINEL_ORDER_ID
            and (row.field or "").startswith(COST_SYNC_FIELD_PREFIX)
        )
        return cls(
            id=row.id,
            order_id=None if (is_unenumerable or is_cost_sync) else row.order_id,
            kind=row.kind,
            field=None if is_unenumerable else row.field,
            ml_value=None if is_unenumerable else row.ml_value,
            gbp_value=None if is_unenumerable else row.gbp_value,
            window_from=row.ml_value if is_unenumerable else None,
            window_to=row.gbp_value if is_unenumerable else None,
            state=row.state,
            assigned_to_id=row.assigned_to_id,
            note=row.note,
            detected_at=row.detected_at,
            updated_at=row.updated_at,
        )


class DivergenceListResponse(BaseModel):
    total: int
    limit: int
    offset: int
    divergences: List[DivergenceSummary]


class DivergenceUpdateRequest(BaseModel):
    state: Optional[str] = Field(default=None, description="One of: " + ", ".join(DIVERGENCE_STATES))
    assigned_to_id: Optional[int] = None
    note: Optional[str] = None


class SaleListItem(BaseModel):
    order_id: int
    pack_id: Optional[int] = None
    status: Optional[str] = None
    date_created: Optional[datetime] = None
    ml_last_updated: Optional[datetime] = None
    buyer_nickname: Optional[str] = None
    total_amount: Optional[float] = None
    paid_amount: Optional[float] = None
    currency_id: Optional[str] = None
    payment_status: Optional[str] = None
    shipping_status: Optional[str] = None
    operation_status: str
    goods_status: str
    neto: Optional[float] = None
    # Resolved cascade (design D1 of ml-ventas-modo-logistico): the real
    # shipment's `logistic_type` ALWAYS outranks the `no_shipping` tag --
    # see `resolve_modo_logistico`. Recomputed live here on every read; no
    # snapshot column exists for this, by design -- the shipment upsert can
    # land after the order's, so a stored mode would be wrong for exactly
    # as long as that gap lasts.
    modo_logistico: str


class SaleGroup(BaseModel):
    """One ROW of the listing: a pack, or a lone order.

    Mercado Libre splits a single purchase into one `order` per item and
    ties them together with `pack_id`. Rendered one-per-row, three orders
    from the same buyer at the same second with different amounts read as
    three unrelated sales -- the operator could not tell what they were
    looking at, and that is what this type exists to fix. Verified live on
    2000018230951686 / 2000018230945962: same `pack_id`, same shipment,
    one physical parcel.

    `group_key` is a STRING, never the bare numeric id. Pack ids and order
    ids are drawn from the same numeric range on ML (`2000014816536209`
    and `2000018230951686` are a pack and an order), so a bare
    `COALESCE(pack_id, order_id)` could collide and silently merge a pack
    with an unrelated order.

    A group's status is its members' only when they AGREE. `"mixed"` is
    not a status either axis defines -- it is this type saying the members
    disagree and the operator has to open the group. Collapsing a
    disagreement into one badge would hide exactly the case worth seeing.
    """

    group_key: str
    pack_id: Optional[int] = None
    date_created: Optional[datetime] = None
    # The MOST RECENT update across the group's orders: a pack is stale only
    # when every one of its parcels is, so `max` is the honest aggregate
    # here, unlike `date_created` which takes the earliest.
    ml_last_updated: Optional[datetime] = None
    buyer_nickname: Optional[str] = None
    total_amount: Optional[float] = None
    currency_id: Optional[str] = None
    operation_status: str
    goods_status: str
    orders: List[SaleListItem]
    neto: Optional[float] = None
    # The group's modo_logistico, collapsed like `operation_status`/
    # `goods_status`: `"mixed"` when the group's orders disagree, never a
    # silently-picked winner (same `_collapse` used by both status axes).
    modo_logistico: str


class SaleFacetCounts(BaseModel):
    """Counts per value of one filter axis, computed WITHIN the scope the
    OTHER active filters leave standing (not the globally unfiltered
    total) -- see `listar_ventas`'s docstring."""

    operation_status: Dict[str, int]
    goods_status: Dict[str, int]
    # The number of ROWS in that axis's scope, which is NOT the sum of its
    # buckets: a pack whose orders disagree counts in two buckets, so the
    # sum double-counts it. The UI's "Todas" chip needs the count of rows
    # it would actually render, or it contradicts the table under it.
    operation_status_total: int = 0
    goods_status_total: int = 0


class SaleListResponse(BaseModel):
    """`total`/`limit`/`offset` count GROUPS, not orders: the listing
    paginates over what it renders, so a pack can never be split across
    two pages."""

    total: int
    limit: int
    offset: int
    sales: List[SaleGroup]
    facets: SaleFacetCounts


# ── Endpoints ────────────────────────────────────────────────────


def _open_claim_exists_subquery(db: Session):
    """Correlated EXISTS: does this order have a linked claim whose status
    is present and NOT settled (`SETTLED_CLAIM_STATUSES`)? Mirrors
    `operation_status.operation_status_of`'s `claim_status` row -- see that
    module for the shared source of truth."""
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
    """SQL `CASE` mirroring `operation_status.operation_status_of` row for
    row -- built from that module's exact `PAID_ORDER_STATUSES`/
    `SETTLED_CLAIM_STATUSES` sets so the two never drift independently."""
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
    """SQL `CASE` mirroring `operation_status.goods_status_of`, built from
    that module's exact `GOODS_STATUS_BY_SHIPPING_STATUS` map."""
    whens = [
        (MlShipmentOps.status == shipping_status, goods_status)
        for shipping_status, goods_status in GOODS_STATUS_BY_SHIPPING_STATUS.items()
    ]
    return case(*whens, else_="unknown")


def _group_key_expr():
    """The listing's grouping key, as TEXT.

    A pack's orders share `pack_id`; a lone order is its own group. The
    prefix is not decoration: ML draws pack ids and order ids from the
    same numeric range, so an unprefixed `COALESCE(pack_id, order_id)`
    can collide and merge a pack with an unrelated order.
    """
    # `||`, not `func.concat`: SQLite only grew a `concat()` function in
    # 3.44, and the integration tests run on SQLite. Passing locally on a
    # newer sqlite would have hidden this until CI.
    return case(
        (MlOrdersOps.pack_id.isnot(None), literal("p:") + cast(MlOrdersOps.pack_id, String)),
        else_=literal("o:") + cast(MlOrdersOps.order_id, String),
    )


def _collapse(values: "list[Optional[str]]") -> str:
    """The members' shared value, or `"mixed"` when they disagree.

    Never silently picks a winner: a pack holding one cancelled order and
    one delivered order is precisely what the operator needs to notice.
    """
    distinct = {v for v in values if v is not None}
    if not distinct:
        return "unknown"
    if len(distinct) == 1:
        return distinct.pop()
    return "mixed"


def _parse_sold_month(sold_month: str) -> Tuple[datetime, datetime]:
    """Parses `YYYY-MM` into a tz-aware `[month_start, next_month_start)`
    range. Raises `HTTPException(422)` for anything else -- never a bare
    `ValueError` reaching the client as a 500."""
    try:
        year_str, month_str = sold_month.split("-", 1)
        year, month = int(year_str), int(month_str)
        if not (1 <= month <= 12):
            raise ValueError("month out of range")
        # Inside the try on purpose: `int("99999")` parses fine and the month
        # check passes, and only `datetime` rejects the year -- outside, that
        # ValueError reached the client as a 500, which is exactly what this
        # function's docstring says cannot happen.
        # Local midnights, for the same reason as `_parse_date_range`: a
        # month is a local idea too, and resolving its edges in UTC moved
        # the first and last evenings of every month into the wrong one.
        tz = ZoneInfo(BUSINESS_TIMEZONE)
        month_start = datetime.combine(date(year, month, 1), time.min, tzinfo=tz)
        days_in_month = calendar.monthrange(year, month)[1]
        next_month_start = datetime.combine(date(year, month, days_in_month) + timedelta(days=1), time.min, tzinfo=tz)
    except (ValueError, OverflowError) as e:
        raise HTTPException(
            status_code=status.HTTP_422_UNPROCESSABLE_ENTITY,
            detail=f"sold_month inválido (esperado YYYY-MM): {sold_month!r}",
        ) from e

    return month_start, next_month_start


SORT_BY_SALE_DATE = "date_created"
SORT_BY_LAST_UPDATE = "ml_last_updated"
SALE_SORTS = (SORT_BY_SALE_DATE, SORT_BY_LAST_UPDATE)


def _parse_date_range(date_from: Optional[str], date_to: Optional[str]) -> Optional[Tuple[datetime, datetime]]:
    """Parses `YYYY-MM-DD` bounds into a tz-aware `[from 00:00, to+1d 00:00)`
    range, so `date_from == date_to` means that whole day rather than an
    empty set.

    Either bound may be omitted: only `date_from` is "from then on", only
    `date_to` is "up to and including that day". Raises `HTTPException(422)`
    for anything unparseable -- never a bare `ValueError` reaching the
    client as a 500, same discipline as `_parse_sold_month`.
    """
    if not date_from and not date_to:
        return None

    def _day(value: str, field: str) -> date:
        try:
            year_str, month_str, day_str = value.split("-")
            return date(int(year_str), int(month_str), int(day_str))
        except (ValueError, OverflowError, TypeError) as e:
            raise HTTPException(
                status_code=status.HTTP_422_UNPROCESSABLE_ENTITY,
                detail=f"{field} inválido (esperado YYYY-MM-DD): {value!r}",
            ) from e

    def _local_midnight(day: date) -> datetime:
        """Midnight of `day` IN THE BUSINESS'S TIMEZONE.

        The column is `timestamptz` holding UTC, which is correct, but the
        day the operator typed is a local day. Resolving it at UTC midnight
        pushes every sale after 21:00 local into the next day -- three hours
        of business landing on the wrong side of the boundary, every day.
        Built from the calendar date and localised, rather than by adding 24
        hours to an instant, so a DST change shifts the boundary instead of
        splitting or duplicating an hour of sales.
        """
        return datetime.combine(day, time.min, tzinfo=ZoneInfo(BUSINESS_TIMEZONE))

    start = _local_midnight(_day(date_from, "date_from")) if date_from else datetime.min.replace(tzinfo=timezone.utc)
    # The exclusive upper bound is the NEXT local midnight, which is what
    # "up to 23:59:59.999" means without having to pick how many nines.
    end = (
        _local_midnight(_day(date_to, "date_to") + timedelta(days=1))
        if date_to
        else datetime.max.replace(tzinfo=timezone.utc)
    )

    if start >= end:
        raise HTTPException(
            status_code=status.HTTP_422_UNPROCESSABLE_ENTITY,
            detail=f"date_from ({date_from!r}) es posterior a date_to ({date_to!r})",
        )
    return start, end


@router.get("/sales", response_model=SaleListResponse)
def listar_ventas(
    operation_status_filter: Optional[str] = Query(default=None, alias="operation_status"),
    goods_status_filter: Optional[str] = Query(default=None, alias="goods_status"),
    sold_month: Optional[str] = Query(default=None, description="YYYY-MM (legacy, usar date_from/date_to)"),
    date_from: Optional[str] = Query(default=None, description="YYYY-MM-DD, inclusive"),
    date_to: Optional[str] = Query(default=None, description="YYYY-MM-DD, inclusive"),
    sort: str = Query(default=SORT_BY_SALE_DATE, description=" | ".join(SALE_SORTS)),
    limit: int = Query(default=50, ge=1, le=200),
    offset: int = Query(default=0, ge=0),
    current_user: Usuario = Depends(require_permission("ml_ops.ver")),
    db: Session = Depends(get_db),
) -> SaleListResponse:
    """The sales list (design: no read-model table -- `ml_orders_ops` is
    already one row per order, `operation_status`/`goods_status` are
    derived query-time via `_operation_status_expr`/`_goods_status_expr`,
    the single source of truth those mirror lives in `operation_status.py`).

    Paginated with a deterministic tiebreaker (`date_created` DESC, then
    `order_id` DESC) -- `date_created` alone is not unique across orders.

    Facet counts (`facets.operation_status`, `facets.goods_status`) are
    each computed WITHIN the scope the OTHER active filters leave
    standing: the `operation_status` facet applies `goods_status`/
    `sold_month` but NOT `operation_status` itself, and vice versa, so a
    facet count answers "how many if I also picked this value" rather than
    a meaningless global total.

    One row per GROUP -- a pack, or a lone order (see `SaleGroup`).
    Everything paginated and counted here is groups, never orders, so a
    pack cannot straddle a page boundary.

    A status filter selects GROUPS: a group is shown when ANY of its
    orders matches, and all of its orders come back regardless. The
    alternative -- filtering the members too -- would render a pack
    missing exactly the order that failed the filter, which is a lie about
    what is in the parcel.

    That also means a pack whose orders disagree counts in BOTH buckets of
    a facet, so the facets can add up to more than `total`. That is the
    honest arithmetic for "how many rows would I see if I picked this",
    which is what a facet count answers.

    Requires `ml_ops.ver`, checked BEFORE the feature flag (403 before
    503) -- same precedent as every other endpoint in this router.
    """
    _require_flag_enabled()

    if operation_status_filter is not None and operation_status_filter not in OPERATION_STATUSES:
        raise HTTPException(
            status_code=status.HTTP_422_UNPROCESSABLE_ENTITY,
            detail=f"operation_status inválido: {operation_status_filter}",
        )
    if goods_status_filter is not None and goods_status_filter not in GOODS_STATUSES:
        raise HTTPException(
            status_code=status.HTTP_422_UNPROCESSABLE_ENTITY,
            detail=f"goods_status inválido: {goods_status_filter}",
        )

    if sort not in SALE_SORTS:
        raise HTTPException(
            status_code=status.HTTP_422_UNPROCESSABLE_ENTITY,
            detail=f"sort inválido: {sort!r} (esperado uno de {', '.join(SALE_SORTS)})",
        )

    # `date_from`/`date_to` win over `sold_month`. The month filter is the
    # older, coarser shape of the same idea and is kept so a bookmarked URL
    # does not 422; sending both would be ambiguous, and silently ANDing
    # them can only ever return less than either asked for.
    sold_range: Optional[Tuple[datetime, datetime]] = _parse_date_range(date_from, date_to)
    if sold_range is None and sold_month:
        sold_range = _parse_sold_month(sold_month)

    open_claim_exists = _open_claim_exists_subquery(db)
    op_status_expr = _operation_status_expr(open_claim_exists)
    goods_status_expr = _goods_status_expr()

    base = db.query(MlOrdersOps, MlShipmentOps).outerjoin(
        MlShipmentOps, MlShipmentOps.shipment_id == MlOrdersOps.shipping_id
    )
    # Always scoped to the configured seller, as the sweep is. Without it
    # every query in this endpoint scans the whole table, and an order
    # belonging to another account would show up in the listing.
    if settings.ML_USER_ID:
        base = base.filter(MlOrdersOps.seller_id == int(settings.ML_USER_ID))
    if sold_range is not None:
        # Filters the SALE date, never the last-update date: "the sales of
        # this week" has to keep meaning the ones sold this week, even when
        # an old one was touched today. Sorting by update is a separate
        # axis -- see `sort`.
        base = base.filter(MlOrdersOps.date_created >= sold_range[0], MlOrdersOps.date_created < sold_range[1])

    # Every order of a group on the page, regardless of the filters that
    # selected that group. Scoped to the seller like everything else.
    members_base = db.query(MlOrdersOps, MlShipmentOps).outerjoin(
        MlShipmentOps, MlShipmentOps.shipment_id == MlOrdersOps.shipping_id
    )
    if settings.ML_USER_ID:
        members_base = members_base.filter(MlOrdersOps.seller_id == int(settings.ML_USER_ID))

    listing_query = base
    if operation_status_filter is not None:
        listing_query = listing_query.filter(op_status_expr == operation_status_filter)
    if goods_status_filter is not None:
        listing_query = listing_query.filter(goods_status_expr == goods_status_filter)

    # Pagination happens over GROUPS, so a pack can never be split across
    # two pages: page the keys first, then fetch every member of those keys.
    group_key = _group_key_expr()
    key_page = (
        listing_query.with_entities(
            group_key.label("group_key"),
            func.min(MlOrdersOps.date_created).label("group_date"),
        )
        .group_by("group_key")
        # The tiebreaker is `max(order_id)`, NOT `group_key`: the key is TEXT,
        # and text ordering puts "o:9" after "o:10". Ordering groups by their
        # key would silently drop the deterministic numeric tiebreaker the
        # per-order listing had, which is what `TestPagination` pins.
        .order_by(
            (
                func.max(MlOrdersOps.ml_last_updated).desc()
                if sort == SORT_BY_LAST_UPDATE
                # `ml_last_updated` is NOT NULL, so it needs no nullslast();
                # `date_created` is nullable and Postgres would otherwise put
                # its NULLs first on a DESC sort.
                else func.min(MlOrdersOps.date_created).desc().nullslast()
            ),
            func.max(MlOrdersOps.order_id).desc(),
        )
        .limit(limit)
        .offset(offset)
        .all()
    )
    page_keys = [row.group_key for row in key_page]

    total = listing_query.with_entities(func.count(func.distinct(group_key))).scalar() or 0

    members_by_key: Dict[str, List[SaleListItem]] = {}
    if page_keys:
        # Deliberately NOT `listing_query`, and NOT `base` either: a filter
        # -- status OR month -- selects which GROUPS to show, never which of
        # their orders to hide. `base` carries `sold_month`, so a pack whose
        # orders straddle midnight on the last day of a month came back
        # missing one: an incomplete parcel presented as a complete one,
        # which is exactly what this query exists to avoid.
        member_rows = (
            members_base.add_columns(
                group_key.label("group_key"),
                op_status_expr.label("operation_status"),
                goods_status_expr.label("goods_status"),
            )
            .filter(group_key.in_(page_keys))
            .order_by(MlOrdersOps.date_created.asc().nullslast(), MlOrdersOps.order_id.asc())
            .all()
        )
        # `neto` for every order on the page, in TWO bulk queries total --
        # never one query per row. See `compute_neto_by_order_ids`'s
        # docstring: same rule `compute_breakdown` applies to a single sale,
        # reused (not reimplemented) here for the whole page at once.
        page_order_ids = [order.order_id for order, _shipment, _key, _op, _goods in member_rows]
        neto_by_order = compute_neto_by_order_ids(db, page_order_ids)
        for order, shipment, key, operation_status_value, goods_status_value in member_rows:
            order_neto = neto_by_order.get(order.order_id)
            # The real shipment ALWAYS outranks the `no_shipping` tag (order
            # 2000016977234624: tagged `no_shipping` AND a delivered
            # `cross_docking` shipment -- the shipment wins). Recomputed
            # live from the already-joined `shipment` row, no new query.
            order_modo_logistico = resolve_modo_logistico(
                shipment_logistic_type=shipment.logistic_type if shipment is not None else None,
                has_shipment=shipment is not None,
                tagged_no_shipping=bool(order.has_no_shipping_tag),
            )
            members_by_key.setdefault(key, []).append(
                SaleListItem(
                    order_id=order.order_id,
                    pack_id=order.pack_id,
                    status=order.status,
                    date_created=order.date_created,
                    ml_last_updated=order.ml_last_updated,
                    buyer_nickname=order.buyer_nickname,
                    total_amount=float(order.total_amount) if order.total_amount is not None else None,
                    paid_amount=float(order.paid_amount) if order.paid_amount is not None else None,
                    currency_id=order.currency_id,
                    payment_status=order.payment_status,
                    shipping_status=shipment.status if shipment is not None else None,
                    operation_status=operation_status_value,
                    goods_status=goods_status_value,
                    neto=float(order_neto) if order_neto is not None else None,
                    modo_logistico=order_modo_logistico,
                )
            )

    groups: List[SaleGroup] = []
    for key in page_keys:
        members = members_by_key.get(key, [])
        if not members:
            continue
        # The pack's own identity, not the first member's: every member of a
        # pack carries the same `pack_id`, and a lone order carries none.
        pack_id = members[0].pack_id
        dates = [m.date_created for m in members if m.date_created is not None]
        amounts = [m.total_amount for m in members if m.total_amount is not None]
        currencies = {m.currency_id for m in members if m.currency_id}
        # Resolved BEFORE the constructor: `currencies.pop()` mutates the set,
        # so reading `len(currencies)` in a later argument would depend on
        # argument evaluation order.
        single_currency = currencies.pop() if len(currencies) == 1 else None
        # The pack's neto is the SUM of its orders' -- `None` if ANY member
        # lacks synced payments, never a partial sum that quietly ignores
        # the missing one. Resolved before the constructor for the same
        # reason `single_currency` is: no mutation inside a call's arguments.
        #
        # `single_currency` gates it for the same reason `total_amount`
        # below is gated: adding ARS to USD produces a number that means
        # nothing. Worse here than there -- a mixed pack would render a
        # null amount beside a numeric net, and the row would read as MORE
        # trustworthy than the honest null next to it.
        member_netos = [m.neto for m in members]
        group_neto = None if (single_currency is None or any(n is None for n in member_netos)) else sum(member_netos)
        groups.append(
            SaleGroup(
                group_key=key,
                pack_id=pack_id,
                neto=group_neto,
                # The earliest member. NOTE this is not always the value the
                # row is sorted by: the sort uses `min` over the FILTERED
                # orders, this uses `min` over all of them. For the pack that
                # straddles a month boundary they differ -- filtering
                # `2026-09` shows `31/08` on a row sorted by `01/09`. Showing
                # the parcel's real date is the right trade; claiming the two
                # always agree was not.
                date_created=min(dates) if dates else None,
                ml_last_updated=(
                    max(u for m in members if (u := m.ml_last_updated) is not None)
                    if any(m.ml_last_updated is not None for m in members)
                    else None
                ),
                buyer_nickname=next((m.buyer_nickname for m in members if m.buyer_nickname), None),
                # A pack is one purchase: its worth is what the buyer paid
                # for all of it, which is why three rows of 27.868 / 27.299 /
                # 24.750 could not be read as the two parcels they were.
                # None across currencies, not a bare sum: adding ARS to USD
                # produces a number that means nothing, and dropping only the
                # currency label would render exactly that number.
                total_amount=float(sum(amounts)) if amounts and single_currency is not None else None,
                currency_id=single_currency,
                operation_status=_collapse([m.operation_status for m in members]),
                goods_status=_collapse([m.goods_status for m in members]),
                modo_logistico=_collapse([m.modo_logistico for m in members]),
                orders=members,
            )
        )

    # Facets: each axis scoped by the OTHER active filter(s), never by its
    # own -- see docstring above.
    op_facet_query = base
    if goods_status_filter is not None:
        op_facet_query = op_facet_query.filter(goods_status_expr == goods_status_filter)
    op_facet_rows = (
        op_facet_query.with_entities(op_status_expr.label("bucket"), func.count(func.distinct(group_key)))
        .group_by("bucket")
        .all()
    )
    op_facet = {value: 0 for value in OPERATION_STATUSES}
    for bucket, count in op_facet_rows:
        op_facet[bucket] = count

    goods_facet_query = base
    if operation_status_filter is not None:
        goods_facet_query = goods_facet_query.filter(op_status_expr == operation_status_filter)
    op_facet_total = op_facet_query.with_entities(func.count(func.distinct(group_key))).scalar() or 0

    goods_facet_rows = (
        goods_facet_query.with_entities(goods_status_expr.label("bucket"), func.count(func.distinct(group_key)))
        .group_by("bucket")
        .all()
    )
    goods_facet = {value: 0 for value in GOODS_STATUSES}
    for bucket, count in goods_facet_rows:
        goods_facet[bucket] = count

    goods_facet_total = goods_facet_query.with_entities(func.count(func.distinct(group_key))).scalar() or 0

    return SaleListResponse(
        total=total,
        limit=limit,
        offset=offset,
        sales=groups,
        facets=SaleFacetCounts(
            operation_status=op_facet,
            goods_status=goods_facet,
            operation_status_total=op_facet_total,
            goods_status_total=goods_facet_total,
        ),
    )


@router.get("/orders/{order_id}", response_model=SaleCentricOperation)
def obtener_operacion(
    order_id: int,
    current_user: Usuario = Depends(require_permission("ml_ops.ver")),
    db: Session = Depends(get_db),
) -> SaleCentricOperation:
    """Sale-centric view: the order plus everything `ml_operation_links`
    resolved to it (shipment, claim, questions, messages) as one operation.
    Requires `ml_ops.ver`. 503 while `ML_ORDERS_OPS_ENABLED` is false."""
    _require_flag_enabled()

    order = db.query(MlOrdersOps).filter(MlOrdersOps.order_id == order_id).first()
    if order is None:
        raise HTTPException(status_code=status.HTTP_404_NOT_FOUND, detail="Orden no encontrada")

    items = db.query(MlOrderItemOps).filter(MlOrderItemOps.order_id == order_id).all()

    shipment = None
    if order.shipping_id is not None:
        shipment = db.query(MlShipmentOps).filter(MlShipmentOps.shipment_id == order.shipping_id).first()

    links = db.query(MlOperationLink).filter(MlOperationLink.order_id == order_id).all()
    claim_ids = [link.entity_id for link in links if link.entity_type == "claim"]
    question_ids = [link.entity_id for link in links if link.entity_type == "question"]
    message_ids = [link.entity_id for link in links if link.entity_type == "message"]

    claim = None
    if claim_ids:
        claim = db.query(RmaClaimML).filter(RmaClaimML.id.in_(claim_ids)).first()

    questions = db.query(MlBotQuestion).filter(MlBotQuestion.id.in_(question_ids)).all() if question_ids else []
    messages = db.query(MlBotMessage).filter(MlBotMessage.id.in_(message_ids)).all() if message_ids else []

    # The breakdown is of the PACK, not just this order -- same grouping
    # `listar_ventas` uses (`_group_key_expr`): a lone order is its own
    # group, an order in a pack shares its breakdown with every sibling.
    if order.pack_id is not None:
        breakdown_order_ids = [
            row.order_id for row in db.query(MlOrdersOps.order_id).filter(MlOrdersOps.pack_id == order.pack_id).all()
        ]
    else:
        breakdown_order_ids = [order.order_id]
    breakdown = compute_breakdown(db, breakdown_order_ids)

    return SaleCentricOperation(
        order=OrderOpsSummary.model_validate(order),
        items=[OrderItemOpsSummary.model_validate(item) for item in items],
        shipment=ShipmentOpsSummary.model_validate(shipment) if shipment else None,
        claim=ClaimSummary.model_validate(claim) if claim else None,
        questions=[QuestionSummary.model_validate(q) for q in questions],
        messages=[MessageSummary.model_validate(m) for m in messages],
        breakdown=OperationBreakdownSummary.from_domain(breakdown),
    )


@router.get("/divergences", response_model=DivergenceListResponse)
def listar_divergencias(
    kind: Optional[str] = Query(default=None, description="Filter by kind"),
    state: Optional[str] = Query(default=None, description="Filter by state"),
    limit: int = Query(default=50, ge=1, le=200),
    offset: int = Query(default=0, ge=0),
    current_user: Usuario = Depends(require_permission("ml_ops.ver")),
    db: Session = Depends(get_db),
) -> DivergenceListResponse:
    """Paginated (slice 4a precedent: every list endpoint MUST paginate).
    Requires `ml_ops.ver`. 503 while `ML_ORDERS_OPS_ENABLED` is false."""
    _require_flag_enabled()

    if kind is not None and kind not in DIVERGENCE_KINDS:
        raise HTTPException(status_code=status.HTTP_422_UNPROCESSABLE_ENTITY, detail=f"kind inválido: {kind}")
    if state is not None and state not in DIVERGENCE_STATES:
        raise HTTPException(status_code=status.HTTP_422_UNPROCESSABLE_ENTITY, detail=f"state inválido: {state}")

    query = db.query(MlOpsDivergence)
    if kind is not None:
        query = query.filter(MlOpsDivergence.kind == kind)
    if state is not None:
        query = query.filter(MlOpsDivergence.state == state)

    total = query.count()
    rows = (
        query.order_by(MlOpsDivergence.detected_at.desc(), MlOpsDivergence.id.desc()).limit(limit).offset(offset).all()
    )

    return DivergenceListResponse(
        total=total,
        limit=limit,
        offset=offset,
        divergences=[DivergenceSummary.from_row(row) for row in rows],
    )


@router.get("/divergences/{divergence_id}", response_model=DivergenceSummary)
def obtener_divergencia(
    divergence_id: int,
    current_user: Usuario = Depends(require_permission("ml_ops.ver")),
    db: Session = Depends(get_db),
) -> DivergenceSummary:
    """Requires `ml_ops.ver`. 503 while `ML_ORDERS_OPS_ENABLED` is false."""
    _require_flag_enabled()

    row = db.query(MlOpsDivergence).filter(MlOpsDivergence.id == divergence_id).first()
    if row is None:
        raise HTTPException(status_code=status.HTTP_404_NOT_FOUND, detail="Divergencia no encontrada")
    return DivergenceSummary.from_row(row)


@router.patch("/divergences/{divergence_id}", response_model=DivergenceSummary)
def actualizar_divergencia(
    divergence_id: int,
    payload: DivergenceUpdateRequest,
    current_user: Usuario = Depends(require_permission("ml_ops.gestionar")),
    db: Session = Depends(get_db),
) -> DivergenceSummary:
    """State/assignee/note changes. Requires `ml_ops.gestionar`, distinct
    from the read-only `ml_ops.ver`. 503 while `ML_ORDERS_OPS_ENABLED` is
    false. Never touches the ML/GBP data the divergence describes -- only
    this row's own bookkeeping (`state`, `assigned_to_id`, `note`)."""
    _require_flag_enabled()

    row = db.query(MlOpsDivergence).filter(MlOpsDivergence.id == divergence_id).first()
    if row is None:
        raise HTTPException(status_code=status.HTTP_404_NOT_FOUND, detail="Divergencia no encontrada")

    # `exclude_unset` via `model_fields_set` distinguishes an ABSENT field
    # (leave alone) from an EXPLICIT `null` (clear it) -- a plain
    # `is not None` check treated both the same, so `{"assigned_to_id":
    # null}` silently did nothing while still returning 200 with the old
    # assignee: the operator believes they released it, and they have not.
    fields_set = payload.model_fields_set

    if "state" in fields_set:
        # `state` is NOT NULL, so an explicit null has to be rejected here.
        # Before absent and null were distinguished, `None` meant "leave
        # alone" and never reached the column; now it does.
        if payload.state not in DIVERGENCE_STATES:
            raise HTTPException(
                status_code=status.HTTP_422_UNPROCESSABLE_ENTITY, detail=f"state inválido: {payload.state}"
            )
        row.state = payload.state
    if "assigned_to_id" in fields_set:
        if payload.assigned_to_id is not None:
            # The column is an FK to usuarios.id; a nonexistent id used to
            # reach `db.commit()` unvalidated and raise IntegrityError --
            # a 500 that also left the session broken. Validated the same
            # way `state` is: reject before touching the row.
            assignee_exists = db.query(Usuario.id).filter(Usuario.id == payload.assigned_to_id).first() is not None
            if not assignee_exists:
                raise HTTPException(
                    status_code=status.HTTP_422_UNPROCESSABLE_ENTITY,
                    detail=f"assigned_to_id inválido: no existe el usuario {payload.assigned_to_id}",
                )
        row.assigned_to_id = payload.assigned_to_id
    if "note" in fields_set:
        row.note = payload.note
    # `updated_at` is NOT set here: the column already has
    # `onupdate=func.now()`, and setting it by hand overwrites the
    # database's clock with the app server's -- two different clocks for
    # one column.

    db.commit()
    db.refresh(row)
    return DivergenceSummary.from_row(row)


@router.post(
    "/activity/ping",
    status_code=status.HTTP_202_ACCEPTED,
    responses={
        202: {"description": "Drain encolado en background; el resultado no vuelve por este request"},
        403: {"description": "Falta el permiso ml_ops.ingest"},
    },
)
def ping_activity(
    background_tasks: BackgroundTasks,
    current_user: Usuario = Depends(require_permission("ml_ops.ingest")),
) -> dict:
    """Ping liviano del bridge ml-webhook (ml-activity-receiver, slice 3):
    encola un drain de `/api/ml/activity` vía `BackgroundTasks` y responde
    202 de inmediato.

    Permiso `ml_ops.ingest` (distinto de `ml_ops.ver`/`ml_ops.gestionar`),
    exclusivo del service user del bridge (slice 1). NO chequea
    `ML_ORDERS_OPS_ENABLED` acá -- a diferencia del resto de este router,
    la bandera apagada es un no-op COMPLETO manejado dentro de
    `drain_activity` (mismo precedente que `backfill_payments_costs_service
    .run_backfill`): el ping sigue devolviendo 202 y el drain encolado no
    hace ningún HTTP ni ninguna escritura, en vez de un 503 que haría que
    un estado deliberadamente apagado se lea como una falla del bridge.

    El cuerpo del request se ignora por completo -- no se declara ningún
    modelo de body, así que FastAPI no lo parsea ni lo valida; este
    endpoint no confía en nada que el bridge le mande en el payload, solo
    en que llegó.

    Un segundo ping mientras un drain ya está en vuelo es inofensivo: el
    lock de corrida (`try_acquire_run_lock`, cursor `ml_activity`) es
    exclusivo por `cursor_name`, así que el segundo background task
    simplemente ve el lock tomado y vuelve sin hacer nada -- nunca dos
    drains concurrentes sobre el mismo cursor.

    `BackgroundTasks` + `get_background_db` (dentro de `drain_activity`),
    NUNCA una sesión de request (`Depends(get_db)`) sostenida durante el
    drain -- este proyecto ya tuvo un incidente de agotamiento del pool de
    conexiones por sostener una sesión de request en un trabajo de larga
    duración (obs `project_db_pool_exhaustion_incident`).
    """
    background_tasks.add_task(drain_activity)
    return {"accepted": True}
