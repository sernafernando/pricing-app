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
"""

from __future__ import annotations

from datetime import date, datetime, time, timedelta, timezone
from decimal import Decimal
from typing import Iterable, List, Optional, Tuple
from zoneinfo import ZoneInfo

from sqlalchemy import BigInteger, Date, Numeric, String, and_, case, cast, func, literal, or_, select
from sqlalchemy.orm import aliased
from sqlalchemy.sql.elements import ColumnElement

from app.core.config import settings
from app.core.constants import BUSINESS_TIMEZONE
from app.models.ml_group_metrics import MlGroupMetrics
from app.models.ml_order_item_costo import MlOrderItemCosto
from app.models.ml_order_metrics import MlOrderMetrics, MlOrderMetricsDirty
from app.models.ml_orders_ops import MlOrderItemOps, MlOrdersOps

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


def _scope(q, ranges: Optional[Iterable[Range]], product: Optional[int]):
    q = q.where(G.group_date.isnot(None))
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


def sale_lines(*, sqlite: bool, ranges: Optional[List[Range]] = None, product: Optional[int] = None):
    """One row per sold item line of every accredited group in `ranges`
    (all history when None), restricted to `product` if given: `product`,
    `mla`, `group_date`, `day`, `qty`, `gross`, `tg` (Total Gauss share),
    `mtg`/`mcosto` (the markup's numerator/denominator share). Cancelled
    sales ML did not cover are left out AFTER the per-order and per-group
    windows, so a pack's markup rule still sees all its members."""
    qty = func.coalesce(I.quantity, 0)
    weight = C.costo_unitario_ars * qty
    # (group, order): the same partitions as by order alone, but sorted the
    # same way as the group window -- one sort serves both windows.
    by_order = {"partition_by": (G.group_key, O.order_id)}
    settled = and_(D.order_id.is_(None), MT.order_id.isnot(None))
    has_gauss = and_(settled, MT.gauss_status.in_(GAUSS_STATUSES), MT.total_gauss.isnot(None))
    candidate = case((and_(has_gauss, MT.costo_mercaderia.isnot(None)), 1), else_=0)
    inner = _scope(
        select(
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
        )
        .select_from(G)
        .join(O, _members_of_group(narrow=product is not None))
        .join(I, I.order_id == O.order_id)
        .outerjoin(C, frozen_cost_of_item())
        .outerjoin(MT, MT.order_id == O.order_id)
        .outerjoin(D, D.order_id == O.order_id),
        ranges,
        product,
    ).subquery("sold")
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
    ).where(x.is_sale == 1)
    if product is not None:
        q = q.where(x.product == product)
    return q.subquery("lines")


def last_sales(*, sqlite: bool, product: Optional[int] = None, ranges: Optional[List[Range]] = None):
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
    )
    if product is not None:
        q = q.where(product_col == product)
    return q.group_by(product_col, I.item_id)
