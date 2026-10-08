"""The filter model of the Publicaciones management screen (design §2) and the base select every view query uses.

`parse_filter` turns the query-string values (csv text) into a frozen `PublicationFilter` and rejects anything
outside the vocabulary with a `FilterError` (the router answers 422). It is pure: no database, no clock.

Rules worth knowing before reading the code:

* Values within one filter OR, different filters AND (spec FLT-1).
* `q` has three shapes (`normalize_q`): an MLA id and a digits-only string are EXACT keys; anything else is a
  case-insensitive substring search. Digits-only is an exact key because it is an MLA number, a seller SKU or an
  EAN, and exact keys use the indexes.
* `gone` and `sin_estado` are status tokens of our own: an item whose `gone_at` is set is listed only when asked
  for with `estado=gone` (and then it is flagged, spec LST-5); `sin_estado` selects items ML sent without a
  status. The status facet offers exactly these values, so every one of them can be selected back.
"""

from __future__ import annotations

import math
import re
from dataclasses import dataclass
from datetime import date, timedelta
from typing import Any, Optional

from sqlalchemy import Interval, and_, case, exists, false, func, literal, or_, select, tuple_
from sqlalchemy.orm import aliased, join as orm_join
from sqlalchemy.sql import ColumnElement, Select

from app.models.ml_publications import (
    MlItem,
    MlItemEvent,
    MlItemProductLink,
    MlItemSalePrice,
    MlItemVariation,
    MlUserProductStock,
)
from app.models.producto import ProductoERP
from app.services.ml_daily_metrics.groups import NO_GROUP

MAX_Q_LENGTH = 100
MIN_ID, MAX_ID = -(2**63), 2**63 - 1  # what the database can hold (bigint): anything beyond is a mistake, not a miss
MAX_CSV_VALUES = 50  # a screen selects a handful; a huge IN (...) list is a mistake or abuse

STATUS_VALUES = ("active", "paused", "closed", "under_review", "inactive")
STATUS_GONE = "gone"  # not an ML status: the item vanished from ML (`gone_at` set)
LISTING_VALUES = ("clasica", "premium", "catalogo", "full")
LINK_VALUES = ("auto", "manual", "sin_producto", "conflicto", "no_evaluado")
STOCK_VALUES = ("sin_stock", "full_sin_stock")
NO_STORE = "none"
NO_STATUS = "sin_estado"

# The event types the store really writes (`services/ml_publications/events.py`); anything else is a typo.
EVENT_TYPES = frozenset(
    {
        "status_paused",
        "status_activated",
        "status_closed",
        "status_under_review",
        "status_changed_other",
        "sub_status_changed",
        "stock_depleted",
        "stock_replenished",
        "price_changed",
        "promotion_offered",
        "promotion_activated",
        "promotion_finished",
        "promotion_price_changed",
        "catalog_competition_won",
        "catalog_competition_lost",
        "moderation_applied",
        "moderation_resolved",
        "product_link_changed",
        "item_gone",
        "item_restored",
    }
)
EVENT_SINCE = {"24h": timedelta(hours=24), "7d": timedelta(days=7), "30d": timedelta(days=30)}

_MLA = re.compile(r"MLA\d+", re.IGNORECASE)
_DIGITS = re.compile(r"\d+")
LIKE_ESCAPE = "\\"


class FilterError(ValueError):
    """A query parameter outside its vocabulary; `field` is the parameter name the client sent."""

    def __init__(self, field: str, message: str) -> None:
        super().__init__(f"{field}: {message}")
        self.field = field
        self.message = message


@dataclass(frozen=True)
class SearchTerm:
    """`kind`: `item_id` (canonical `MLA123`), `digits` (exact key) or `text` (substring)."""

    kind: str
    value: str


@dataclass(frozen=True)
class PublicationFilter:
    q: Optional[SearchTerm] = None
    status: tuple[str, ...] = ()
    status_exclude: tuple[str, ...] = ()
    stores: tuple[int, ...] = ()
    no_store: bool = False
    marcas: tuple[str, ...] = ()
    categorias: tuple[str, ...] = ()
    subcategorias: tuple[int, ...] = ()
    no_subcategoria: bool = False  # `__none__` among the subcategories: the products with no subcategory
    pms: tuple[int, ...] = ()
    # (marca, categoria) pairs of `pms`, trimmed and upper-cased (by the database); resolved against the database
    # by `listing.resolve_pm_pairs`.
    # `None` while unresolved; an empty tuple means the PMs own no pair, which matches nothing.
    pm_pairs: Optional[tuple[tuple[str, str], ...]] = None
    family_id: Optional[int] = None
    # A node of the Agrupado tree (P7a): one linked product, or the publications with no product at all.
    producto: Optional[int] = None
    sin_producto: bool = False
    listing: tuple[str, ...] = ()
    link: tuple[str, ...] = ()
    stock: tuple[str, ...] = ()
    event_types: tuple[str, ...] = ()
    event_since: Optional[timedelta] = None

    @property
    def needs_events(self) -> bool:
        """The event filter reads `ml_item_events`, which is only populated while `events.enabled` is on."""
        return bool(self.event_types)


# --- q ------------------------------------------------------------------------------------------------


def normalize_q(raw: Optional[str]) -> Optional[SearchTerm]:
    term = (raw or "").strip()
    if not term:
        return None
    if len(term) > MAX_Q_LENGTH:
        raise FilterError("q", f"at most {MAX_Q_LENGTH} characters")
    if _MLA.fullmatch(term):
        return SearchTerm("item_id", term.upper())
    if _DIGITS.fullmatch(term):
        return SearchTerm("digits", term)
    return SearchTerm("text", term)


def escape_like(text: str) -> str:
    """`text` with the LIKE wildcards and the escape character made literal (pair with `escape=LIKE_ESCAPE`)."""
    return text.replace(LIKE_ESCAPE, LIKE_ESCAPE * 2).replace("%", LIKE_ESCAPE + "%").replace("_", LIKE_ESCAPE + "_")


# --- csv params -----------------------------------------------------------------------------------------


def _tokens(raw: Optional[str], field: str) -> list[str]:
    seen: dict[str, None] = {}
    for token in (raw or "").split(","):
        token = token.strip()
        if token:
            seen.setdefault(token)
    if len(seen) > MAX_CSV_VALUES:
        raise FilterError(field, f"at most {MAX_CSV_VALUES} values")
    return list(seen)


def _vocabulary(field: str, raw: Optional[str], allowed: tuple[str, ...] | frozenset[str]) -> tuple[str, ...]:
    tokens = _tokens(raw, field)
    unknown = [t for t in tokens if t not in allowed]
    if unknown:
        known = ", ".join(sorted(allowed))
        raise FilterError(field, f"unknown value(s) {', '.join(unknown)}; known: {known}")
    return tuple(tokens)


def _integer(field: str, token: str) -> int:
    try:
        value = int(token)
    except ValueError:
        raise FilterError(field, f"{token!r} is not a number") from None
    if not MIN_ID <= value <= MAX_ID:
        raise FilterError(field, f"{token!r} is out of range")
    return value


def _integers(field: str, raw: Optional[str]) -> tuple[int, ...]:
    return tuple(_integer(field, t) for t in _tokens(raw, field))


def _store_ids(raw: Optional[str]) -> tuple[tuple[int, ...], bool]:
    tokens = _tokens(raw, "tiendas")
    return tuple(_integer("tiendas", t) for t in tokens if t != NO_STORE), NO_STORE in tokens


def _subcategorias(raw: Optional[str]) -> tuple[tuple[int, ...], bool]:
    tokens = _tokens(raw, "subcategorias")
    return tuple(_integer("subcategorias", t) for t in tokens if t != NO_GROUP), NO_GROUP in tokens


def _producto(raw: Optional[str]) -> Optional[int]:
    tokens = _tokens(raw, "producto")
    if not tokens:
        return None
    if len(tokens) > 1:
        raise FilterError("producto", "a single product id")
    return _integer("producto", tokens[0])


def _family(raw: Optional[str]) -> Optional[int]:
    tokens = _tokens(raw, "familia")
    if not tokens:
        return None
    if len(tokens) > 1:
        raise FilterError("familia", "a single family id")
    return _integer("familia", tokens[0])


def _event_since(raw: Optional[str], has_events: bool) -> Optional[timedelta]:
    token = (raw or "").strip()
    if not token:
        return None
    if token not in EVENT_SINCE:
        raise FilterError("evento_desde", f"unknown value {token!r}; known: {', '.join(EVENT_SINCE)}")
    if not has_events:
        raise FilterError("evento_desde", "requires `evento`")
    return EVENT_SINCE[token]


def parse_filter(
    *,
    q: Optional[str] = None,
    estado: Optional[str] = None,
    estado_excluir: Optional[str] = None,
    tiendas: Optional[str] = None,
    marcas: Optional[str] = None,
    categorias: Optional[str] = None,
    subcategorias: Optional[str] = None,
    pms: Optional[str] = None,
    familia: Optional[str] = None,
    producto: Optional[str] = None,
    sin_producto: Optional[bool] = None,
    tipo: Optional[str] = None,
    vinculo: Optional[str] = None,
    stock: Optional[str] = None,
    evento: Optional[str] = None,
    evento_desde: Optional[str] = None,
) -> PublicationFilter:
    """Query-string values (csv text, `None` when absent) -> `PublicationFilter`; `FilterError` when invalid."""
    status_vocabulary = (*STATUS_VALUES, STATUS_GONE, NO_STATUS)
    stores, no_store = _store_ids(tiendas)
    event_types = _vocabulary("evento", evento, EVENT_TYPES)
    subcategorias_, no_subcategoria = _subcategorias(subcategorias)
    return PublicationFilter(
        q=normalize_q(q),
        status=_vocabulary("estado", estado, status_vocabulary),
        status_exclude=_vocabulary("estado_excluir", estado_excluir, status_vocabulary),
        stores=stores,
        no_store=no_store,
        marcas=tuple(_tokens(marcas, "marcas")),
        categorias=tuple(_tokens(categorias, "categorias")),
        subcategorias=subcategorias_,
        no_subcategoria=no_subcategoria,
        pms=_integers("pms", pms),
        family_id=_family(familia),
        producto=_producto(producto),
        sin_producto=bool(sin_producto),
        listing=_vocabulary("tipo", tipo, LISTING_VALUES),
        link=_vocabulary("vinculo", vinculo, LINK_VALUES),
        stock=_vocabulary("stock", stock, STOCK_VALUES),
        event_types=event_types,
        event_since=_event_since(evento_desde, bool(event_types)),
    )


# --- markup filters (applied after the markup is computed, not in SQL) -------------------------------------------


@dataclass(frozen=True)
class MarkupFilter:
    """`markup_neg` / `markup_min` / `markup_max` (addendum decision 5): ANY variation negative, and a range over
    the WORST variation. A publication without a markup value matches none of them."""

    negative: bool = False
    minimum: Optional[float] = None
    maximum: Optional[float] = None

    @property
    def active(self) -> bool:
        return self.negative or self.minimum is not None or self.maximum is not None

    def accepts(self, worst: Optional[float], any_negative: bool) -> bool:
        if not self.active:
            return True
        if worst is None:
            return False
        if self.negative and not any_negative:
            return False
        if self.minimum is not None and worst < self.minimum:
            return False
        return self.maximum is None or worst <= self.maximum


def _number(field: str, raw: Optional[str]) -> Optional[float]:
    token = (raw or "").strip()
    if not token:
        return None
    try:
        value = float(token)
    except ValueError:
        raise FilterError(field, f"{token!r} is not a number") from None
    if not math.isfinite(value):
        raise FilterError(field, f"{token!r} is not a finite number")
    return value


def parse_markup_filter(
    *, markup_neg: Optional[bool] = None, markup_min: Optional[str] = None, markup_max: Optional[str] = None
) -> MarkupFilter:
    minimum, maximum = _number("markup_min", markup_min), _number("markup_max", markup_max)
    if minimum is not None and maximum is not None and minimum > maximum:
        raise FilterError("markup_min", "must not be greater than markup_max")
    return MarkupFilter(bool(markup_neg), minimum, maximum)


def _day(field: str, raw: Optional[str]) -> Optional[date]:
    token = (raw or "").strip()
    if not token:
        return None
    try:
        return date.fromisoformat(token)
    except ValueError:
        raise FilterError(field, f"{token!r} is not a date (YYYY-MM-DD)") from None


def parse_ads_period(ads_desde: Optional[str], ads_hasta: Optional[str]) -> tuple[Optional[date], Optional[date]]:
    """The period whose Ads cost is spread over the units sold in it: both ends or neither, first <= last."""
    first, last = _day("ads_desde", ads_desde), _day("ads_hasta", ads_hasta)
    if (first is None) != (last is None):
        raise FilterError("ads_hasta" if last is None else "ads_desde", "give both ads_desde and ads_hasta")
    if first is not None and last is not None and first > last:
        raise FilterError("ads_desde", "must not be after ads_hasta")
    return first, last


# --- the base select ----------------------------------------------------------------------------------------
#
# One SELECT over `ml_items` with LEFT JOINs that are each unique on their join key (so none can multiply a row):
# the current sale price, the ITEM-LEVEL link (variation 0), the linked product and the per-user-product stock.
# This is the only view module that names the product catalog: see the exception in `test_static_guards.py`.

LINK_ITEM_LEVEL = 0
LINK_LINKED = "linked"
LINK_CONFLICT = "conflict"
LINK_SOURCE_MANUAL = "manual"
FULFILLMENT = "fulfillment"
LISTING_CLASSIC = "gold_special"
LISTING_PREMIUM = "gold_pro"

AXES = ("status", "stores", "marcas", "listing", "link", "stock")


class T:
    """The aliased tables of the base select."""

    i = aliased(MlItem, name="i")
    sp = aliased(MlItemSalePrice, name="sp")
    l = aliased(MlItemProductLink, name="l")  # noqa: E741 -- the design names the link table `l`
    p = aliased(ProductoERP, name="p")
    st = aliased(MlUserProductStock, name="st")
    v = aliased(MlItemVariation, name="v")
    e = aliased(MlItemEvent, name="e")


def joined() -> Any:
    return orm_join(
        orm_join(
            orm_join(
                orm_join(
                    T.i,
                    T.sp,
                    and_(T.sp.item_id == T.i.item_id, T.sp.gone_at.is_(None), T.sp.http_status.between(200, 299)),
                    isouter=True,
                ),
                T.l,
                and_(T.l.item_id == T.i.item_id, T.l.variation_id == LINK_ITEM_LEVEL),
                isouter=True,
            ),
            T.p,
            T.p.item_id == T.l.producto_item_id,
            isouter=True,
        ),
        T.st,
        T.st.user_product_id == T.i.user_product_id,
        isouter=True,
    )


def price_amount() -> ColumnElement:
    """The ML price of the row: the sale price when there is one, else the item price (spec PRC-1)."""
    return func.coalesce(T.sp.amount, T.i.price)


def status_value() -> ColumnElement:
    """The status axis value of a row: `gone` for a vanished item, else its ML status (`sin_estado` when none)."""
    return case((T.i.gone_at.isnot(None), literal(STATUS_GONE)), else_=func.coalesce(T.i.status, literal(NO_STATUS)))


def link_state() -> ColumnElement:
    # ponytail: only the item-level link (variation 0) is read, so an item whose links are all per variation
    # reads `no_evaluado`; the variation sub-rows (P6c) are where those links show up
    return case(
        (T.l.item_id.is_(None), literal("no_evaluado")),
        (T.l.match_status == LINK_CONFLICT, literal("conflicto")),
        (and_(T.l.match_status == LINK_LINKED, T.l.source == LINK_SOURCE_MANUAL), literal("manual")),
        (T.l.match_status == LINK_LINKED, literal("auto")),
        else_=literal("sin_producto"),
    )


def _status(f: PublicationFilter) -> ColumnElement:
    """`estado` / `estado_excluir`: ML statuses plus two tokens of ours, `gone` (vanished from ML) and
    `sin_estado` (no status). Gone items are shown only when `gone` is asked for."""
    wanted = [s for s in f.status if s not in (STATUS_GONE, NO_STATUS)]
    live = []
    if wanted:
        live.append(T.i.status.in_(wanted))
    if NO_STATUS in f.status:
        live.append(T.i.status.is_(None))
    parts = [and_(T.i.gone_at.is_(None), or_(*live))] if live else []
    if STATUS_GONE in f.status:
        parts.append(T.i.gone_at.isnot(None))
    clause = or_(*parts) if parts else T.i.gone_at.is_(None)
    excluded = [s for s in f.status_exclude if s not in (STATUS_GONE, NO_STATUS)]
    if NO_STATUS in f.status_exclude:
        clause = and_(clause, T.i.status.isnot(None))
    if excluded:  # a NULL status is not one of the excluded values: it stays unless `sin_estado` is excluded too
        clause = and_(clause, or_(T.i.status.is_(None), T.i.status.notin_(excluded)))
    if STATUS_GONE in f.status_exclude:
        clause = and_(clause, T.i.gone_at.is_(None))
    return clause


def _variation_sku(match: Any) -> ColumnElement:
    return exists(
        select(1).where(
            T.v.item_id == T.i.item_id,
            T.v.gone_at.is_(None),
            or_(match(T.v.seller_sku), match(T.v.seller_custom_field)),
        )
    )


def _search(term: SearchTerm) -> ColumnElement:
    if term.kind == "item_id":
        return T.i.item_id == term.value
    if term.kind == "digits":

        def same(column: Any) -> ColumnElement:
            return column == term.value

        return or_(
            T.i.item_id == f"MLA{term.value}",
            same(T.i.seller_sku),
            same(T.i.seller_custom_field),
            same(T.p.codigo),
            _variation_sku(same),
        )
    # ponytail: case-insensitive but accent-sensitive; `unaccent` is not installed on the test DB and its presence
    # on production is unverified (`scripts/measure_pubml_p5.py --database-url` reports it)
    pattern = f"%{escape_like(term.value)}%"

    def contains(column: Any) -> ColumnElement:
        return column.ilike(pattern, escape=LIKE_ESCAPE)

    return or_(
        contains(T.i.title),
        contains(T.i.seller_sku),
        contains(T.i.seller_custom_field),
        contains(T.p.codigo),
        contains(T.p.descripcion),
        _variation_sku(contains),
    )


def listing_clauses() -> dict[str, ColumnElement]:
    return {
        "clasica": T.i.listing_type_id == LISTING_CLASSIC,
        "premium": T.i.listing_type_id == LISTING_PREMIUM,
        "catalogo": T.i.catalog_listing.is_(True),
        "full": T.i.logistic_type == FULFILLMENT,
    }


def stock_clauses() -> dict[str, ColumnElement]:
    # `full_sin_stock` is a real zero: a user product without a stock row has an unknown Full stock, not none.
    return {"sin_stock": T.i.available_quantity == 0, "full_sin_stock": T.st.full_quantity == 0}


def _any_of(clauses: dict[str, ColumnElement], values: tuple[str, ...]) -> ColumnElement:
    return or_(*(clauses[v] for v in values))


def _stores(f: PublicationFilter) -> ColumnElement:
    parts = []
    if f.stores:
        parts.append(T.i.official_store_id.in_(f.stores))
    if f.no_store:
        parts.append(T.i.official_store_id.is_(None))
    return or_(*parts)


_ESCAPES = {"%": "%25", ",": "%2C"}
_ESCAPED = re.compile(r"%(25|2C)")


def encode_key(text: str) -> str:
    """A brand or category key as it travels in a CSV parameter: `%` and `,` percent-escaped, so a name holding a
    comma stays ONE value. The tree and the brand facet hand out keys in this form."""
    return "".join(_ESCAPES.get(char, char) for char in text)


def decode_key(token: str) -> str:
    """The inverse of `encode_key` (a single pass: `%252C` is the text `%2C`)."""
    return _ESCAPED.sub(lambda match: chr(int(match.group(1), 16)), token)


def normalized_text(column: Any) -> ColumnElement:
    """A brand or category as the tree keys it (and the PM pairs are matched): trimmed and upper-cased. No index is
    lost by this: the catalog only has plain btrees on `marca` / `categoria`, which `upper(...)` already bypassed."""
    return func.upper(func.trim(func.coalesce(column, "")))


def _text_in(column: Any, wanted: tuple[str, ...]) -> ColumnElement:
    """`marcas` / `categorias`: the value as the tree keys it (trimmed, upper-cased; `NO_GROUP` for none), so the
    node of a brand and the filter that lists its publications agree on which rows they mean."""
    # upper-cased by the database too, never by Python: the two disagree on some letters (the sharp s), and the
    # tree's keys come from the database
    values = [normalized_text(literal(decode_key(w))) for w in wanted if w != NO_GROUP]
    parts = []
    if values:
        parts.append(normalized_text(column).in_(values))
    if NO_GROUP in wanted:
        parts.append(normalized_text(column) == "")
    return or_(*parts)


def _subcategorias_in(f: PublicationFilter) -> ColumnElement:
    parts = []
    if f.subcategorias:
        parts.append(T.p.subcategoria_id.in_(f.subcategorias))
    if f.no_subcategoria:
        parts.append(T.p.subcategoria_id.is_(None))
    return or_(*parts)


def _pm(f: PublicationFilter) -> ColumnElement:
    if f.pm_pairs is None:
        raise RuntimeError("`pms` must be resolved to pairs (listing.resolve_pm_pairs) before building the query")
    if not f.pm_pairs:
        return false()  # a PM that owns no (marca, categoria) pair matches nothing, never everything
    return tuple_(normalized_text(T.p.marca), normalized_text(T.p.categoria)).in_(list(f.pm_pairs))


def _event(f: PublicationFilter) -> ColumnElement:
    where = [T.e.item_id == T.i.item_id, T.e.event_type.in_(f.event_types)]
    if f.event_since is not None:
        where.append(T.e.observed_at >= func.now() - literal(f.event_since, Interval))
    return exists(select(1).where(*where))


def conditions(f: PublicationFilter, skip: Optional[str] = None) -> list[ColumnElement]:
    """The WHERE of a filter. `skip` names an axis (one of `AXES`) whose own selection is left out: a facet
    counts the rows each of ITS values would give while every other filter still applies. Skipping `status` also
    lifts the default hiding of gone items, so their count can be offered as the `gone` value."""
    where: list[ColumnElement] = [T.i.never_existed.isnot(True)]
    if skip != "status":  # the status facet offers every status, `gone` included, whatever is selected
        where.append(_status(f))
    if f.q is not None:
        where.append(_search(f.q))
    if (f.stores or f.no_store) and skip != "stores":
        where.append(_stores(f))
    if f.marcas and skip != "marcas":
        where.append(_text_in(T.p.marca, f.marcas))
    if f.categorias:
        where.append(_text_in(T.p.categoria, f.categorias))
    if f.subcategorias or f.no_subcategoria:
        where.append(_subcategorias_in(f))
    if f.producto is not None:
        where.append(T.p.item_id == f.producto)
    if f.sin_producto:
        where.append(T.p.item_id.is_(None))
    if f.pms:
        where.append(_pm(f))
    if f.family_id is not None:
        where.append(T.i.family_id == f.family_id)
    if f.listing and skip != "listing":
        where.append(_any_of(listing_clauses(), f.listing))
    if f.link and skip != "link":
        where.append(link_state().in_(f.link))
    if f.stock and skip != "stock":
        where.append(_any_of(stock_clauses(), f.stock))
    if f.event_types:
        where.append(_event(f))
    return where


def build_base_select(f: PublicationFilter, *columns: Any, skip: Optional[str] = None) -> Select:
    """`SELECT <columns> FROM ml_items i LEFT JOIN ... WHERE <filter>`; no ORDER BY, no paging."""
    return select(*columns).select_from(joined()).where(*conditions(f, skip))
