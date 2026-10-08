"""The filter model of the Publicaciones management screen (design §2) and the base select every view query uses.

`parse_filter` turns the query-string values (csv text) into a frozen `PublicationFilter` and rejects anything
outside the vocabulary with a `FilterError` (the router answers 422). It is pure: no database, no clock.

Rules worth knowing before reading the code:

* Values within one filter OR, different filters AND (spec FLT-1).
* `q` has three shapes (`normalize_q`): an MLA id and a digits-only string are EXACT keys; anything else is a
  case-insensitive substring search. Digits-only is an exact key because it is an MLA number, a seller SKU or an
  EAN, and exact keys use the indexes.
* `gone` is a status token of its own: an item whose `gone_at` is set is listed only when asked for with
  `estado=gone`, and then it is flagged (spec LST-5).
"""

from __future__ import annotations

import re
from dataclasses import dataclass
from datetime import timedelta
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

MAX_Q_LENGTH = 100

STATUS_VALUES = ("active", "paused", "closed", "under_review", "inactive")
STATUS_GONE = "gone"  # not an ML status: the item vanished from ML (`gone_at` set)
LISTING_VALUES = ("clasica", "premium", "catalogo", "full")
LINK_VALUES = ("auto", "manual", "sin_producto", "conflicto", "no_evaluado")
STOCK_VALUES = ("sin_stock", "full_sin_stock")
NO_STORE = "none"

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
    pms: tuple[int, ...] = ()
    # (marca, categoria) pairs of `pms`, upper-cased; resolved against the database by `listing.resolve_pm_pairs`.
    # `None` while unresolved; an empty tuple means the PMs own no pair, which matches nothing.
    pm_pairs: Optional[tuple[tuple[str, str], ...]] = None
    family_id: Optional[int] = None
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


def _tokens(raw: Optional[str]) -> list[str]:
    seen: dict[str, None] = {}
    for token in (raw or "").split(","):
        token = token.strip()
        if token:
            seen.setdefault(token)
    return list(seen)


def _vocabulary(field: str, raw: Optional[str], allowed: tuple[str, ...] | frozenset[str]) -> tuple[str, ...]:
    tokens = _tokens(raw)
    unknown = [t for t in tokens if t not in allowed]
    if unknown:
        known = ", ".join(sorted(allowed))
        raise FilterError(field, f"unknown value(s) {', '.join(unknown)}; known: {known}")
    return tuple(tokens)


def _integer(field: str, token: str) -> int:
    try:
        return int(token)
    except ValueError:
        raise FilterError(field, f"{token!r} is not a number") from None


def _integers(field: str, raw: Optional[str]) -> tuple[int, ...]:
    return tuple(_integer(field, t) for t in _tokens(raw))


def _store_ids(raw: Optional[str]) -> tuple[tuple[int, ...], bool]:
    tokens = _tokens(raw)
    return tuple(_integer("tiendas", t) for t in tokens if t != NO_STORE), NO_STORE in tokens


def _family(raw: Optional[str]) -> Optional[int]:
    tokens = _tokens(raw)
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
    tipo: Optional[str] = None,
    vinculo: Optional[str] = None,
    stock: Optional[str] = None,
    evento: Optional[str] = None,
    evento_desde: Optional[str] = None,
) -> PublicationFilter:
    """Query-string values (csv text, `None` when absent) -> `PublicationFilter`; `FilterError` when invalid."""
    status_vocabulary = (*STATUS_VALUES, STATUS_GONE)
    stores, no_store = _store_ids(tiendas)
    event_types = _vocabulary("evento", evento, EVENT_TYPES)
    return PublicationFilter(
        q=normalize_q(q),
        status=_vocabulary("estado", estado, status_vocabulary),
        status_exclude=_vocabulary("estado_excluir", estado_excluir, status_vocabulary),
        stores=stores,
        no_store=no_store,
        marcas=tuple(_tokens(marcas)),
        categorias=tuple(_tokens(categorias)),
        subcategorias=_integers("subcategorias", subcategorias),
        pms=_integers("pms", pms),
        family_id=_family(familia),
        listing=_vocabulary("tipo", tipo, LISTING_VALUES),
        link=_vocabulary("vinculo", vinculo, LINK_VALUES),
        stock=_vocabulary("stock", stock, STOCK_VALUES),
        event_types=event_types,
        event_since=_event_since(evento_desde, bool(event_types)),
    )


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


def link_state() -> ColumnElement:
    return case(
        (T.l.item_id.is_(None), literal("no_evaluado")),
        (T.l.match_status == LINK_CONFLICT, literal("conflicto")),
        (and_(T.l.match_status == LINK_LINKED, T.l.source == LINK_SOURCE_MANUAL), literal("manual")),
        (T.l.match_status == LINK_LINKED, literal("auto")),
        else_=literal("sin_producto"),
    )


def _status(f: PublicationFilter) -> ColumnElement:
    wanted = [s for s in f.status if s != STATUS_GONE]
    parts = []
    if wanted:
        parts.append(and_(T.i.gone_at.is_(None), T.i.status.in_(wanted)))
    if STATUS_GONE in f.status:
        parts.append(T.i.gone_at.isnot(None))
    clause = or_(*parts) if parts else T.i.gone_at.is_(None)
    excluded = [s for s in f.status_exclude if s != STATUS_GONE]
    if excluded:
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


def _pm(f: PublicationFilter) -> ColumnElement:
    if f.pm_pairs is None:
        raise RuntimeError("`pms` must be resolved to pairs (listing.resolve_pm_pairs) before building the query")
    if not f.pm_pairs:
        return false()  # a PM that owns no (marca, categoria) pair matches nothing, never everything
    return tuple_(func.upper(T.p.marca), func.upper(T.p.categoria)).in_(list(f.pm_pairs))


def _event(f: PublicationFilter) -> ColumnElement:
    where = [T.e.item_id == T.i.item_id, T.e.event_type.in_(f.event_types)]
    if f.event_since is not None:
        where.append(T.e.observed_at >= func.now() - literal(f.event_since, Interval))
    return exists(select(1).where(*where))


def conditions(f: PublicationFilter, skip: Optional[str] = None) -> list[ColumnElement]:
    """The WHERE of a filter. `skip` names an axis (one of `AXES`) whose own selection is left out: a facet
    counts the rows each of ITS values would give while every other filter still applies."""
    where: list[ColumnElement] = [T.i.never_existed.isnot(True)]
    where.append(_status(f) if skip != "status" else T.i.gone_at.is_(None))
    if f.q is not None:
        where.append(_search(f.q))
    if (f.stores or f.no_store) and skip != "stores":
        where.append(_stores(f))
    if f.marcas and skip != "marcas":
        where.append(func.upper(T.p.marca).in_([m.upper() for m in f.marcas]))
    if f.categorias:
        where.append(func.upper(T.p.categoria).in_([c.upper() for c in f.categorias]))
    if f.subcategorias:
        where.append(T.p.subcategoria_id.in_(f.subcategorias))
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
