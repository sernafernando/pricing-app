"""The ONE per-sold-item base the Métricas ML board reads (ODD
`metricas-ml-tablero`, "Sin tabla resumen"): straight from the tables we
already have -- orders, items, frozen costs, stored metrics and the group's
accreditation day -- never a derived summary table.

Rules (the Ventas ML ones, so both screens agree on the same orders):

- DAY of a sale = its GROUP's accreditation (`ml_group_metrics.group_date`,
  MAX date_approved of the relevant payments of every member), read as a
  Buenos Aires calendar day. A group with no accreditation is in no day.
- PRODUCT of an item = its frozen cost row (`frozen_cost_of_item()`), or
  `NO_PRODUCT` (0) when it has none.
- A sale cancelled WITHOUT Mercado Libre covering it is not a sale; one ML
  covered (`covered_by_marketplace`) is.
- TOTAL GAUSS (and the markup) only from `ok`/`provisional` orders: Ventas
  ML's reader enforces "unresolved => no Total Gauss" (`OrderMetrics`), so an
  unresolved order never adds Total Gauss nor enters the markup there; the
  board decides by the status too, so a row breaking that invariant cannot
  leak into the sums.
- MONEY only from orders whose stored metrics are settled: an order being
  recalculated (a dirty row), parked (failed) or never computed (no
  `ml_order_metrics` row) adds units but no gross, Total Gauss or cost --
  same exclusion as `ml_sales_query/aggregate.py`.
- Gross = items' `unit_price x quantity`, ARS orders only.
- An order's Total Gauss and cost of goods are split across its items by
  frozen-cost share (`costo_unitario_ars x quantity`); a lone item takes it
  all; unknown or zero weights fall back to quantity, and an all-zero
  quantity to equal parts.
- MARKUP numerator/denominator: all-or-nothing PER GROUP (pack), like the
  Ventas ML KPI: a group contributes only when every member order carries
  both Total Gauss and cost and is settled (`mtg`/`mcosto`). Total Gauss
  shown on its own (`tg`) still includes every known value.
- TP-LINK (`tg_tp`/`mtg_tp`/`mcosto_tp`, only with `tp=True`): the same
  split and the same rules, from the order's stored Total TP and TP cost.
  NULL means unknown, never 0: an order without a TP cost, or without a
  Total Gauss at all (unresolved, never computed, queued for a recompute --
  Total TP needs Total Gauss), and the markup shares of a group that does
  not take part in the TP markup.
"""

from __future__ import annotations

from datetime import date, datetime, time, timedelta, timezone
from decimal import Decimal
from typing import Any, Callable, Iterable, List, Optional, Sequence, Tuple
from zoneinfo import ZoneInfo

from sqlalchemy import BigInteger, Date, Numeric, String, and_, case, cast, func, literal, null, or_, select, union
from sqlalchemy.orm import aliased
from sqlalchemy.sql.elements import ColumnElement

from app.core.config import settings
from app.core.constants import BUSINESS_TIMEZONE
from app.models.ml_group_metrics import MlGroupMetrics
from app.models.ml_order_item_costo import MlOrderItemCosto
from app.models.ml_order_metrics import MlOrderMetrics, MlOrderMetricsDirty
from app.models.ml_orders_ops import MlOrderItemOps, MlOrdersOps
from app.models.ml_sale_line import MlSaleLine

BUSINESS_TZ = ZoneInfo(BUSINESS_TIMEZONE)
NO_PRODUCT = 0

G = MlGroupMetrics
O = MlOrdersOps  # noqa: E741 -- the orders table, as in the SQL
I = MlOrderItemOps  # noqa: E741
C = MlOrderItemCosto
MT = MlOrderMetrics
D = MlOrderMetricsDirty

# A UTC range `[start, end)` of group accreditation timestamps; `end=None`
# means open-ended.
Range = Tuple[datetime, Optional[datetime]]


# A predicate over a sold line, given its item (`ml_order_items_ops`) and frozen
# cost (`ml_order_item_costos`) rows: what `groups_touching` reads.
LinePredicate = Callable[[Any, Any], ColumnElement[bool]]


# The stored statuses whose Total Gauss is a number (`unresolved` never is).
GAUSS_STATUSES = ("ok", "provisional")


def _numeric(expr, sqlite: bool):
    """`expr` as an exact decimal for a division: NUMERIC on Postgres. SQLite
    has no decimal type (and its CAST AS NUMERIC keeps an integer, so the
    division would truncate): a REAL there, where tests round anyway."""
    return expr * 1.0 if sqlite else cast(expr, Numeric)


def frozen_cost_of_item(cost=MlOrderItemCosto, item=MlOrderItemOps) -> ColumnElement[bool]:
    """The ONE join from a sold item (`ml_order_items_ops`) to its frozen
    cost row (`ml_order_item_costos`): same order, same MLA, same variation
    (NULL matching NULL). Matching on (order, MLA) alone pairs each
    variation with every other variation's cost and double counts."""
    return and_(
        cost.order_id == item.order_id,
        cost.item_id == item.item_id,
        or_(
            cost.variation_id == item.variation_id,
            and_(cost.variation_id.is_(None), item.variation_id.is_(None)),
        ),
    )


def business_day(moment: datetime) -> date:
    """The business-timezone calendar day of a timestamp (naive = UTC, which
    is what SQLite hands back for a tz-aware column)."""
    if moment.tzinfo is None:
        moment = moment.replace(tzinfo=timezone.utc)
    return moment.astimezone(BUSINESS_TZ).date()


def day_bounds(first: date, last: date) -> Tuple[datetime, datetime]:
    """`[first 00:00, last+1 00:00)` in the business timezone, as UTC: SQLite
    drops the offset of a bound tz-aware value, so a business-midnight bound
    would silently compare as UTC midnight there."""
    start = datetime.combine(first, time.min, tzinfo=BUSINESS_TZ).astimezone(timezone.utc)
    end = datetime.combine(last + timedelta(days=1), time.min, tzinfo=BUSINESS_TZ).astimezone(timezone.utc)
    return start, end


def business_date(expr, sqlite: bool):
    """SQL: the business-timezone calendar day of a timestamptz."""
    if sqlite:
        # SQLite keeps the UTC wall clock as text. Buenos Aires has no DST
        # (fixed UTC-3), so a fixed offset is exact there.
        offset = datetime.now(BUSINESS_TZ).utcoffset() or timedelta(0)
        return func.date(expr, f"{int(offset.total_seconds() // 3600):+d} hours")
    return cast(func.timezone(BUSINESS_TIMEZONE, expr), Date)


def group_key_expr(order=MlOrdersOps):
    """`p:<pack_id>` or `o:<order_id>`: the key of `ml_group_metrics`."""
    return case(
        (order.pack_id.isnot(None), literal("p:") + cast(order.pack_id, String)),
        else_=literal("o:") + cast(order.order_id, String),
    )


def _members_of_group(narrow: bool):
    """The orders of a group row. Two equivalent spellings, each for the
    plan it allows:

    - wide (the whole board, tens of thousands of groups): equality on the
      group key, so Postgres can HASH-join every order once;
    - narrow (one product's groups): `p:<id>` = every order of that pack,
      `o:<id>` = that lone order, so each group reaches its orders through
      the `pack_id`/`order_id` indexes instead of hashing every order."""
    if not narrow:
        return group_key_expr() == G.group_key
    number = cast(func.substr(G.group_key, 3), BigInteger)
    return or_(
        and_(G.group_key.like("p:%"), O.pack_id == number),
        and_(G.group_key.like("o:%"), O.order_id == number, O.pack_id.is_(None)),
    )


def _is_a_sale():
    """Cancelled without ML coverage is not a sale (NULL status is)."""
    return or_(O.status.is_(None), O.status != "cancelled", O.covered_by_marketplace.is_(True))


def groups_touching(predicates: Sequence[LinePredicate]):
    """The keys of the groups that have at least one sold line passing ANY of
    `predicates`: `group_key`, one row per group. Each predicate is its own
    semi-join (one `OR` across the item and product tables would hide their
    indexes from the planner). Whole groups: the per-order and per-group
    windows of `sale_lines` still see every member."""
    parts = []
    for predicate in predicates:
        o2, i2, c2 = aliased(MlOrdersOps), aliased(MlOrderItemOps), aliased(MlOrderItemCosto)
        parts.append(
            select(group_key_expr(o2).label("group_key"))
            .select_from(o2)
            .join(i2, i2.order_id == o2.order_id)
            .outerjoin(c2, frozen_cost_of_item(c2, i2))
            .where(predicate(i2, c2))
        )
    return union(*parts) if len(parts) > 1 else parts[0].distinct()


def _scope(q, ranges: Optional[Iterable[Range]], product: Optional[int], groups: Optional[Any] = None):
    q = q.where(G.group_date.isnot(None))
    if groups is not None:
        q = q.where(G.group_key.in_(groups))
    if ranges is not None:
        q = q.where(
            or_(
                *(
                    and_(G.group_date >= start, G.group_date < end) if end is not None else G.group_date >= start
                    for start, end in ranges
                )
            )
        )
    if settings.ML_USER_ID:
        q = q.where(O.seller_id == int(settings.ML_USER_ID))
    if product is not None and product != NO_PRODUCT:
        # Only the groups that sold this product: reached through the frozen
        # costs' product index, never by scanning every group.
        o2, c2 = aliased(MlOrdersOps), aliased(MlOrderItemCosto)
        q = q.where(
            G.group_key.in_(
                select(group_key_expr(o2)).join(c2, c2.order_id == o2.order_id).where(c2.producto_item_id == product)
            )
        )
    return q


def sale_lines(
    *,
    sqlite: bool,
    ranges: Optional[List[Range]] = None,
    product: Optional[int] = None,
    groups: Optional[Any] = None,
    queue: bool = True,
    keyed: bool = False,
    narrow: bool = False,
    tp: bool = False,
):
    """One row per sold item line of every accredited group in `ranges`
    (all history when None), restricted to `product` if given: `product`,
    `mla`, `group_date`, `day`, `qty`, `gross`, `tg` (Total Gauss share),
    `mtg`/`mcosto` (the markup's numerator/denominator share). Cancelled
    sales ML did not cover are left out AFTER the per-order and per-group
    windows, so a pack's markup rule still sees all its members.

    `groups` (a one-column select of group keys, see `groups_touching`) limits
    the read to those groups BELOW the windows: a small selection reads its own
    orders, not every order of the period. The groups come whole, with their
    other lines too: the caller keeps filtering the lines it wants.

    `queue=False` ignores the recompute queue (`ml_order_metrics_dirty`): an
    order is then settled when it HAS stored metrics, whether or not it is being
    recalculated -- the persisted `ml_sale_lines` are written that way, and the
    board puts the queue back at read time. `keyed=True` adds the columns that
    identify a line (`item_row_id`, `order_id`, `group_key`); `narrow=True`
    reaches the orders of a small `groups` set through their indexes instead of
    hashing every order. `tp=True` adds the TP-Link shares (`tg_tp`, `mtg_tp`,
    `mcosto_tp`). Two callers ask for them: the `ml_sale_lines` writer
    (`queue=False`) and the board's live derivation with "Costos TP" ON (through
    `lines_source`, queue applied); without `tp` the SQL carries none of them."""
    qty = func.coalesce(I.quantity, 0)
    weight = C.costo_unitario_ars * qty
    # (group, order): the same partitions as by order alone, but sorted the
    # same way as the group window -- one sort serves both windows.
    by_order = {"partition_by": (G.group_key, O.order_id)}
    settled = and_(D.order_id.is_(None), MT.order_id.isnot(None)) if queue else MT.order_id.isnot(None)
    has_gauss = and_(settled, MT.gauss_status.in_(GAUSS_STATUSES), MT.total_gauss.isnot(None))
    candidate = case((and_(has_gauss, MT.costo_mercaderia.isnot(None)), 1), else_=0)
    # A group takes part in the TP markup when every member also has Total TP
    # and TP cost.
    candidate_tp = case(
        (and_(has_gauss, MT.costo_mercaderia.isnot(None), MT.total_tp.isnot(None), MT.costo_tp.isnot(None)), 1),
        else_=0,
    )
    tp_source = (
        [
            MT.total_tp.label("order_tp"),
            MT.costo_tp.label("order_costo_tp"),
            func.min(candidate_tp).over(partition_by=G.group_key).label("eligible_tp"),
        ]
        if tp
        else []
    )
    identity = (
        [I.id.label("item_row_id"), O.order_id.label("order_id"), G.group_key.label("group_key")] if keyed else []
    )
    source = (
        select(
            *identity,
            func.coalesce(C.producto_item_id, NO_PRODUCT).label("product"),
            I.item_id.label("mla"),
            G.group_date.label("group_date"),
            business_date(G.group_date, sqlite).label("day"),
            qty.label("qty"),
            I.unit_price.label("unit_price"),
            func.coalesce(O.currency_id, "ARS").label("currency"),
            case((_is_a_sale(), 1), else_=0).label("is_sale"),
            case((settled, 1), else_=0).label("settled"),
            case((has_gauss, 1), else_=0).label("has_gauss"),
            MT.total_gauss.label("order_tg"),
            MT.costo_mercaderia.label("order_costo"),
            weight.label("weight"),
            func.count().over(**by_order).label("n"),
            func.count(weight).over(**by_order).label("n_weighted"),
            func.sum(weight).over(**by_order).label("weight_sum"),
            func.sum(qty).over(**by_order).label("qty_sum"),
            func.min(candidate).over(partition_by=G.group_key).label("eligible"),
            *tp_source,
        )
        .select_from(G)
        .join(O, _members_of_group(narrow=narrow or product is not None))
        .join(I, I.order_id == O.order_id)
        .outerjoin(C, frozen_cost_of_item())
        .outerjoin(MT, MT.order_id == O.order_id)
    )
    if queue:
        source = source.outerjoin(D, D.order_id == O.order_id)
    inner = _scope(source, ranges, product, groups).subquery("sold")
    x = inner.c
    # NUMERIC in every branch: one float branch makes Postgres resolve the
    # whole CASE -- and every money sum after it -- to double precision.
    share = case(
        (x.n == 1, literal(Decimal(1), Numeric)),
        (and_(x.n_weighted == x.n, x.weight_sum != 0), _numeric(x.weight, sqlite) / x.weight_sum),
        (x.qty_sum != 0, _numeric(x.qty, sqlite) / x.qty_sum),
        else_=_numeric(literal(1), sqlite) / x.n,
    )
    eligible = x.eligible == 1
    q = select(
        *([x.item_row_id, x.order_id, x.group_key] if keyed else []),
        x.product,
        x.mla,
        x.group_date,
        x.day,
        x.qty,
        case(
            (and_(x.settled == 1, x.currency == "ARS", x.unit_price.isnot(None)), x.unit_price * x.qty), else_=0
        ).label("gross"),
        case((x.has_gauss == 1, x.order_tg * share), else_=0).label("tg"),
        case((eligible, x.order_tg * share), else_=0).label("mtg"),
        case((eligible, x.order_costo * share), else_=0).label("mcosto"),
        *(_tp_shares(x, share) if tp else []),
    ).where(x.is_sale == 1)
    if product is not None:
        q = q.where(x.product == product)
    return q.subquery("lines")


def _tp_shares(x, share) -> list:
    """`tg_tp`, `mtg_tp`, `mcosto_tp` of a line: `tg`/`mtg`/`mcosto` with the
    order's Total TP and TP cost, NULL wherever they are unknown -- never 0.
    `tg_tp` is NULL for an order without a known Total TP: no TP cost
    (`order_tp` NULL) or no Total Gauss (unresolved, never computed, or queued
    when the queue applies), since Total TP = Total Gauss + cost - TP cost.
    `mtg_tp`/`mcosto_tp` are NULL for a group that does not take part in the TP
    markup (all-or-nothing, like `mtg`/`mcosto`, whose 0 means the same)."""
    eligible_tp = x.eligible_tp == 1
    unknown = cast(null(), Numeric)
    return [
        case((x.has_gauss == 1, x.order_tp * share), else_=unknown).label("tg_tp"),
        case((eligible_tp, x.order_tp * share), else_=unknown).label("mtg_tp"),
        case((eligible_tp, x.order_costo_tp * share), else_=unknown).label("mcosto_tp"),
    ]


def last_sales(
    *,
    sqlite: bool,
    product: Optional[int] = None,
    ranges: Optional[List[Range]] = None,
    groups: Optional[Any] = None,
):
    """`product`, `mla`, `last_at`: the latest accredited sale of every pair,
    over ALL history (or only `ranges`) -- what ageing and "última venta"
    read. Same base as `sale_lines` (same day, product and cancellation
    rules) without the money, so it needs no windows."""
    product_col = func.coalesce(C.producto_item_id, NO_PRODUCT)
    q = _scope(
        select(product_col.label("product"), I.item_id.label("mla"), func.max(G.group_date).label("last_at"))
        .select_from(G)
        .join(O, _members_of_group(narrow=product is not None))
        .join(I, I.order_id == O.order_id)
        .outerjoin(C, frozen_cost_of_item())
        .where(_is_a_sale()),
        ranges,
        product,
        groups,
    )
    if product is not None:
        q = q.where(product_col == product)
    return q.group_by(product_col, I.item_id)


def _in_ranges(column, ranges: Optional[Iterable[Range]]):
    """`column` inside any of `ranges` (`[start, end)`, `end=None` open)."""
    return or_(*(and_(column >= start, column < end) if end is not None else column >= start for start, end in ranges))


def persisted_lines(
    *,
    ranges: Optional[List[Range]] = None,
    product: Optional[int] = None,
    mlas: Optional[Any] = None,
    tp: bool = False,
    keyed: bool = False,
):
    """The same lines as `sale_lines` (same columns, same numbers), read from the
    persisted `ml_sale_lines` instead of derived: no joins, no windows. The table
    is written as if every order were settled; the recompute queue is applied here,
    as the live derivation does: an order being recalculated has no gross and no
    Total Gauss, and its group takes no part in the markup (no `mtg`, no `mcosto`).
    `mlas` (a list or a one-column select) limits it to those MLAs: each line is
    independent, so no other line of the group is needed. `tp=True` adds the
    TP-Link shares under the same queue rule, but NULL (unknown) where the
    Gauss columns say 0, as the live derivation does. `keyed=True` adds the line's
    `item_row_id`, `order_id` and `group_key`."""
    L = MlSaleLine
    o2 = aliased(MlOrdersOps)
    queued_orders = select(D.order_id)
    queued_groups = select(group_key_expr(o2)).select_from(o2).join(D, D.order_id == o2.order_id)
    order_queued, group_queued = L.order_id.in_(queued_orders), L.group_key.in_(queued_groups)
    q = select(
        *([L.item_row_id, L.order_id, L.group_key] if keyed else []),
        L.product,
        L.mla,
        L.group_date,
        L.day,
        L.qty,
        case((order_queued, 0), else_=L.gross).label("gross"),
        case((order_queued, 0), else_=L.tg).label("tg"),
        case((group_queued, 0), else_=L.mtg).label("mtg"),
        case((group_queued, 0), else_=L.mcosto).label("mcosto"),
        *(
            [
                # Queued: Total TP unknown until recomputed -- NULL (incomplete), never 0.
                case((order_queued, cast(null(), Numeric)), else_=L.tg_tp).label("tg_tp"),
                case((group_queued, cast(null(), Numeric)), else_=L.mtg_tp).label("mtg_tp"),
                case((group_queued, cast(null(), Numeric)), else_=L.mcosto_tp).label("mcosto_tp"),
            ]
            if tp
            else []
        ),
    )
    if ranges is not None:
        q = q.where(_in_ranges(L.group_date, ranges))
    if product is not None:
        q = q.where(L.product == product)
    if mlas is not None:
        q = q.where(L.mla.in_(mlas))
    return q.subquery("lines")


def reads_persisted_lines(sqlite: bool) -> bool:
    """Whether the sold lines come from the persisted `ml_sale_lines` (behind
    `METRICAS_SALE_LINES_ENABLED`, PostgreSQL only: the drain writes the table)
    instead of being derived live. One switch for every reader of the lines."""
    return bool(settings.METRICAS_SALE_LINES_ENABLED) and not sqlite


def lines_source(
    *,
    sqlite: bool,
    ranges: Optional[List[Range]] = None,
    product: Optional[int] = None,
    groups: Optional[Any] = None,
    mlas: Optional[Any] = None,
    tp: bool = False,
    keyed: bool = False,
):
    """The sold lines (`sale_lines` columns) from the source `reads_persisted_lines`
    picks. `groups` bounds only the live derivation and `mlas` only the persisted
    read: the persisted lines are independent rows, while the live ones need their
    whole groups (the caller still keeps the lines of its MLAs there). `tp=True`
    adds the TP-Link shares (`tg_tp`, `mtg_tp`, `mcosto_tp`) from either source, `keyed=True`
    the line's `item_row_id`, `order_id` and `group_key`."""
    if reads_persisted_lines(sqlite):
        return persisted_lines(ranges=ranges, product=product, mlas=mlas, tp=tp, keyed=keyed)
    return sale_lines(sqlite=sqlite, ranges=ranges, product=product, groups=groups, tp=tp, keyed=keyed)


def persisted_last_sales(
    *, product: Optional[int] = None, ranges: Optional[List[Range]] = None, mlas: Optional[Any] = None
):
    """`last_sales` from the persisted lines: `product`, `mla`, `last_at`, over ALL
    history (or only `ranges`). `mlas` (a one-column select) limits it to those MLAs."""
    L = MlSaleLine
    q = select(L.product.label("product"), L.mla.label("mla"), func.max(L.group_date).label("last_at"))
    if ranges is not None:
        q = q.where(_in_ranges(L.group_date, ranges))
    if product is not None:
        q = q.where(L.product == product)
    if mlas is not None:
        q = q.where(L.mla.in_(mlas))
    return q.group_by(L.product, L.mla)
