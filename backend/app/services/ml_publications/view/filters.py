"""The filter model of the Publicaciones management screen (design §2) and the base select every view query uses.

`parse_filter` turns the query-string values (csv text) into a frozen `PublicationFilter` and rejects anything
outside the vocabulary with a `FilterError` (the router answers 422). It is pure: no database, no clock.

Rules worth knowing before reading the code:

* Values within one filter OR, different filters AND (spec FLT-1).
* `q` has three shapes (`normalize_q`): an MLA id and a digits-only string are EXACT keys; anything else is a
  case-insensitive substring search. Digits-only is an exact key because it is an MLA number, a seller SKU or an
  EAN, and exact keys use the indexes.
* `gone` and `sin_estado` are status tokens of our own: a deleted item (`gone_at` set, or `deleted` in ML's
  `sub_status`, see `deleted()`) is listed only when asked for with `estado=gone` (and then it is flagged, spec
  LST-5); `sin_estado` selects items ML sent without a status. The status facet offers exactly these values, so
  every one of them can be selected back.
"""

from __future__ import annotations

import math
import re
from dataclasses import dataclass
from datetime import UTC, date, datetime, time, timedelta
from typing import Any, Optional
from zoneinfo import ZoneInfo

from sqlalchemy import (
    ARRAY,
    Integer,
    Interval,
    String,
    all_,
    and_,
    any_,
    case,
    exists,
    false,
    func,
    literal,
    not_,
    or_,
    select,
    true,
    tuple_,
)
from sqlalchemy.orm import aliased, join as orm_join
from sqlalchemy.sql import ColumnElement, Select

from app.models.auditoria import Auditoria, TipoAccion
from app.models.ml_publications import (
    MlItem,
    MlItemEvent,
    MlItemProductLink,
    MlItemSalePrice,
    MlItemVariation,
    MlUserProductStock,
)
from app.models.oferta_ml import OfertaML
from app.models.producto import ProductoERP, ProductoPricing
from app.models.tienda_nube_producto import TiendaNubeProducto
from app.services.ml_daily_metrics.groups import NO_GROUP, pm_pairs
from app.services.ml_publications.events import EVENT_TYPES as real_event_types
from app.services.ml_publications.links import sku_divergence

MAX_Q_LENGTH = 100
MIN_ID, MAX_ID = -(2**63), 2**63 - 1  # what the database can hold (bigint): anything beyond is a mistake, not a miss
MAX_CSV_VALUES = 50  # a screen selects a handful; a huge IN (...) list is a mistake or abuse

STATUS_VALUES = ("active", "paused", "closed", "under_review", "inactive")
STATUS_GONE = "gone"  # not an ML status: the item vanished from ML (`gone_at` set)
LISTING_VALUES = ("clasica", "premium", "catalogo", "full")
# `sku_divergente` is not a link state: it selects the automatic links whose seller SKU disagrees with the linked
# product (`links.sku_divergence`), a subset of `auto`.
LINK_SKU_DIVERGENT = "sku_divergente"
LINK_STATES = ("auto", "manual", "sin_producto", "conflicto", "no_evaluado")
LINK_VALUES = (*LINK_STATES, LINK_SKU_DIVERGENT)
STOCK_VALUES = ("sin_stock", "full_sin_stock", "erp_sin_stock", "erp_con_stock", "propio_sin_stock")
# Productos' row colors (`productos_colors.COLORES_VALIDOS`) and its "no color" sentinel.
COLOR_VALUES = ("rojo", "naranja", "amarillo", "verde", "azul", "purpura", "gris")
NO_COLOR = "sin_color"
NO_STORE = "none"
NO_STATUS = "sin_estado"

# The event types the store really writes (`events.EVENT_TYPES`, the one list); anything else is a typo.
EVENT_TYPES = frozenset(real_event_types)
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
    """`kind`: `item_id` (canonical `MLA123`), `digits` (exact key), `text` (substring), or one of Productos'
    operators: `codigo` (`codigo:` / `ean:`, the exact product code), `marca` (`marca:`, the exact brand) and
    `ends_with` (`*X`)."""

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
    # A PM node of the Agrupado tree: the products whose (marca, categoria) pair the tree gives to this user id
    # (the lowest id of the pair, `pm_pairs`), or `NO_GROUP` for the products with no PM. Unlike `pms`, a pair listed
    # for several PMs belongs to exactly ONE of them, so the node and its publications agree.
    pm_group: Optional[str] = None
    family_id: Optional[int] = None
    # A node of the Agrupado tree (P7a) or a Producto row: one linked product -- the LINK's product id, even when the
    # product is gone from the catalog -- or the publications whose item-level link names no product at all.
    producto: Optional[int] = None
    sin_producto: bool = False
    listing: tuple[str, ...] = ()
    link: tuple[str, ...] = ()
    stock: tuple[str, ...] = ()
    event_types: tuple[str, ...] = ()
    event_since: Optional[timedelta] = None
    # Productos' "Filtros de Presencia" (`presence_conditions`): `None` = no filter, else the side asked for.
    rebate: Optional[bool] = None
    oferta: Optional[bool] = None
    web_transf: Optional[bool] = None
    out_of_cards: Optional[bool] = None
    tienda_nube: Optional[str] = None  # one of `TIENDA_NUBE_STATES`
    precio: Optional[bool] = None  # Productos' "con precio": the product has a `precio_lista_ml`
    nuevos: bool = False  # Productos' "Nuevos (7 días)": the product was synced from the ERP in the last 7 days
    # Productos' markup filters: (stored `productos_pricing` markup column, positive?) of the linked product. A margin
    # figure: the router asks `ml_metricas.ver_ganancia` before parsing them.
    markup_signs: tuple[tuple[str, bool], ...] = ()
    # Productos' audit filter: the linked product has an `auditoria` row by one of these users, of one of these kinds
    # (`TipoAccion` values), within [since, until] (naive UTC, the column's; parsed from Buenos Aires wall time).
    audit_users: tuple[int, ...] = ()
    audit_kinds: tuple[str, ...] = ()
    audit_since: Optional[datetime] = None
    audit_until: Optional[datetime] = None

    # The promo and PxQ filters, resolved by the router to the matching MLAs (mlwebhook database): `None` = no such
    # filter, an empty set lists nothing.
    mla_scope: Optional[frozenset[str]] = None

    @property
    def audits(self) -> bool:
        return bool(self.audit_users or self.audit_kinds or self.audit_since or self.audit_until)

    # The Producto view asks mejor oferta of the PRODUCT (any of its publications, as Productos does); the
    # publication list asks it of each publication. `oferta_por_producto` asks it of the product elsewhere too: the
    # Producto view's rows carry it in their `params` and its KPI strip sends it, so both agree with the rows.
    oferta_per_product: bool = False
    # Productos' color filter (`colores`): the products painted one of `colors` on the layer on show, plus the
    # unpainted ones (and the publications with no product) with `no_color`. The colors live with Productos' tables,
    # so the router resolves them first (`ml_publication_colors.resolve_color_filter`): `color_ids` are the products
    # with one of `colors`, `colored_ids` every painted product of the layer. `None` while unresolved.
    colors: tuple[str, ...] = ()
    no_color: bool = False
    color_ids: Optional[tuple[int, ...]] = None
    colored_ids: Optional[tuple[int, ...]] = None

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
    field, sep, value = term.partition(":")
    value = value.strip()
    if sep and value and not value.startswith("*") and field.strip().lower() in _OPERATORS:
        return SearchTerm(_OPERATORS[field.strip().lower()], value)
    if term.startswith("*") and term[1:].strip():
        return SearchTerm("ends_with", term[1:].strip())
    return SearchTerm("text", term)


# Productos' search operators (`productos_listing.py`): `ean:` is the same code column there too
_OPERATORS = {"codigo": "codigo", "ean": "codigo", "marca": "marca"}


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


def _pm_group(raw: Optional[str]) -> Optional[str]:
    tokens = _tokens(raw, "pm_grupo")
    if not tokens:
        return None
    if len(tokens) > 1:
        raise FilterError("pm_grupo", "a single user id, or __none__")
    if tokens[0] == NO_GROUP:
        return NO_GROUP
    return str(_integer("pm_grupo", tokens[0]))


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


TIENDA_NUBE_STATES = ("con_descuento", "sin_descuento", "no_publicado")


def _tienda_nube(
    con_descuento: Optional[bool], sin_descuento: Optional[bool], no_publicado: Optional[bool]
) -> Optional[str]:
    """Productos' three Tienda Nube flags, read the way Productos reads them: the first one set wins."""
    for state, on in zip(TIENDA_NUBE_STATES, (con_descuento, sin_descuento, no_publicado)):
        if on:
            return state
    return None


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
    pm_grupo: Optional[str] = None,
    familia: Optional[str] = None,
    producto: Optional[str] = None,
    sin_producto: Optional[bool] = None,
    tipo: Optional[str] = None,
    vinculo: Optional[str] = None,
    stock: Optional[str] = None,
    evento: Optional[str] = None,
    evento_desde: Optional[str] = None,
    con_rebate: Optional[bool] = None,
    con_oferta: Optional[bool] = None,
    con_web_transf: Optional[bool] = None,
    tn_con_descuento: Optional[bool] = None,
    tn_sin_descuento: Optional[bool] = None,
    tn_no_publicado: Optional[bool] = None,
    out_of_cards: Optional[bool] = None,
    oferta_por_producto: Optional[bool] = None,
    con_precio: Optional[bool] = None,
    nuevos_ultimos_7_dias: Optional[bool] = None,
    markup_clasica_positivo: Optional[bool] = None,
    markup_rebate_positivo: Optional[bool] = None,
    markup_oferta_positivo: Optional[bool] = None,
    markup_web_transf_positivo: Optional[bool] = None,
    audit_usuarios: Optional[str] = None,
    audit_tipos_accion: Optional[str] = None,
    audit_fecha_desde: Optional[str] = None,
    audit_fecha_hasta: Optional[str] = None,
    mla_scope: Optional[frozenset[str]] = None,
    colores: Optional[str] = None,
) -> PublicationFilter:
    """Query-string values (csv text, `None` when absent) -> `PublicationFilter`; `FilterError` when invalid."""
    status_vocabulary = (*STATUS_VALUES, STATUS_GONE, NO_STATUS)
    stores, no_store = _store_ids(tiendas)
    event_types = _vocabulary("evento", evento, EVENT_TYPES)
    subcategorias_, no_subcategoria = _subcategorias(subcategorias)
    colores_ = _vocabulary("colores", colores, (*COLOR_VALUES, NO_COLOR))
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
        pm_group=_pm_group(pm_grupo),
        family_id=_family(familia),
        producto=_producto(producto),
        sin_producto=bool(sin_producto),
        listing=_vocabulary("tipo", tipo, LISTING_VALUES),
        link=_vocabulary("vinculo", vinculo, LINK_VALUES),
        stock=_vocabulary("stock", stock, STOCK_VALUES),
        event_types=event_types,
        event_since=_event_since(evento_desde, bool(event_types)),
        rebate=con_rebate,
        oferta=con_oferta,
        web_transf=con_web_transf,
        out_of_cards=out_of_cards,
        tienda_nube=_tienda_nube(tn_con_descuento, tn_sin_descuento, tn_no_publicado),
        oferta_per_product=bool(oferta_por_producto),
        precio=con_precio,
        nuevos=bool(nuevos_ultimos_7_dias),
        markup_signs=tuple(
            (column, positive)
            for column, positive in (
                ("markup_calculado", markup_clasica_positivo),
                ("markup_rebate", markup_rebate_positivo),
                ("markup_oferta", markup_oferta_positivo),
                ("markup_web_real", markup_web_transf_positivo),
            )
            if positive is not None
        ),
        audit_users=_integers("audit_usuarios", audit_usuarios),
        audit_kinds=_vocabulary("audit_tipos_accion", audit_tipos_accion, AUDIT_KINDS),
        audit_since=_audit_moment("audit_fecha_desde", audit_fecha_desde, end_of_day=False),
        audit_until=_audit_moment("audit_fecha_hasta", audit_fecha_hasta, end_of_day=True),
        mla_scope=mla_scope,
        colors=tuple(c for c in colores_ if c != NO_COLOR),
        no_color=NO_COLOR in colores_,
    )


AUDIT_KINDS = frozenset(kind.value for kind in TipoAccion)
_AUDIT_FORMATS = ("%Y-%m-%d %H:%M:%S", "%Y-%m-%d %H:%M", "%Y-%m-%dT%H:%M")
_BUENOS_AIRES = ZoneInfo("America/Argentina/Buenos_Aires")


def _audit_moment(field: str, raw: Optional[str], *, end_of_day: bool) -> Optional[datetime]:
    """Productos' audit dates: `YYYY-MM-DD[ HH:MM[:SS]]` in Buenos Aires wall time (a bare date is the whole day:
    from 00:00, or until 23:59:59; an until without seconds is the whole minute), as naive UTC like
    `auditoria.fecha`. Anything else is an error, never "today"."""
    text_ = (raw or "").strip()
    if not text_:
        return None
    moment = None
    for fmt in _AUDIT_FORMATS:
        try:
            moment = datetime.strptime(text_, fmt)
            if end_of_day and "%S" not in fmt:
                moment = moment.replace(second=59)
            break
        except ValueError:
            continue
    if moment is None:
        try:
            day = date.fromisoformat(text_)
        except ValueError as exc:
            raise FilterError(field, "expected YYYY-MM-DD or YYYY-MM-DD HH:MM") from exc
        moment = datetime.combine(day, time(23, 59, 59) if end_of_day else time.min)
    return moment.replace(tzinfo=_BUENOS_AIRES).astimezone(UTC).replace(tzinfo=None)


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
# the current sale price, the ITEM-LEVEL link (variation 0), the linked product, the product the link's SKU suggests
# (`ps`, read only by the SKU divergence) and the per-user-product stock.
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
    ps = aliased(ProductoERP, name="ps")  # the product the link's seller SKU names (the stored suggestion)
    st = aliased(MlUserProductStock, name="st")
    v = aliased(MlItemVariation, name="v")
    e = aliased(MlItemEvent, name="e")


def joined() -> Any:
    priced = orm_join(
        T.i,
        T.sp,
        and_(T.sp.item_id == T.i.item_id, T.sp.gone_at.is_(None), T.sp.http_status.between(200, 299)),
        isouter=True,
    )
    linked = orm_join(priced, T.l, and_(T.l.item_id == T.i.item_id, T.l.variation_id == LINK_ITEM_LEVEL), isouter=True)
    products = orm_join(
        orm_join(linked, T.p, T.p.item_id == T.l.producto_item_id, isouter=True),
        T.ps,
        T.ps.item_id == T.l.suggested_producto_item_id,
        isouter=True,
    )
    return orm_join(products, T.st, T.st.user_product_id == T.i.user_product_id, isouter=True)


def price_amount() -> ColumnElement:
    """The ML price of the row: the sale price when there is one, else the item price (spec PRC-1)."""
    return func.coalesce(T.sp.amount, T.i.price)


def deleted() -> ColumnElement:
    """A deleted item, the `gone` status token: it vanished from ML (`gone_at` set), or ML marks it deleted in its
    `sub_status` (ML keeps a deleted item as `inactive`/`closed` with `deleted` there, and never sets our `gone_at`)."""
    # IS TRUE: on a NULL sub_status `= ANY` is NULL, and NOT of it would hide every live item without a sub_status
    return or_(T.i.gone_at.isnot(None), T.i.sub_status.any("deleted").is_(true()))


def status_value() -> ColumnElement:
    """The status axis value of a row: `gone` for a deleted item, else its ML status (`sin_estado` when none)."""
    return case((deleted(), literal(STATUS_GONE)), else_=func.coalesce(T.i.status, literal(NO_STATUS)))


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


def link_divergence() -> ColumnElement:
    """The SKU divergence kind of the row's item-level link (`links.sku_divergence`), else NULL."""
    return sku_divergence(T.l)


def _link(f: PublicationFilter) -> ColumnElement:
    """`vinculo`: the link states asked for, OR the SKU-divergent links when `sku_divergente` is among them."""
    states = [value for value in f.link if value != LINK_SKU_DIVERGENT]
    parts = [link_state().in_(states)] if states else []
    if LINK_SKU_DIVERGENT in f.link:
        parts.append(link_divergence().isnot(None))
    return or_(*parts)


def _status(f: PublicationFilter) -> ColumnElement:
    """`estado` / `estado_excluir`: ML statuses plus two tokens of ours, `gone` (vanished from ML) and
    `sin_estado` (no status). Deleted items (`deleted()`) are shown only when `gone` is asked for."""
    wanted = [s for s in f.status if s not in (STATUS_GONE, NO_STATUS)]
    live = []
    if wanted:
        live.append(T.i.status.in_(wanted))
    if NO_STATUS in f.status:
        live.append(T.i.status.is_(None))
    parts = [and_(not_(deleted()), or_(*live))] if live else []
    if STATUS_GONE in f.status:
        parts.append(deleted())
    clause = or_(*parts) if parts else not_(deleted())
    excluded = [s for s in f.status_exclude if s not in (STATUS_GONE, NO_STATUS)]
    if NO_STATUS in f.status_exclude:
        clause = and_(clause, T.i.status.isnot(None))
    if excluded:  # a NULL status is not one of the excluded values: it stays unless `sin_estado` is excluded too
        clause = and_(clause, or_(T.i.status.is_(None), T.i.status.notin_(excluded)))
    if STATUS_GONE in f.status_exclude:
        clause = and_(clause, not_(deleted()))
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
    if term.kind == "codigo":
        return func.upper(T.p.codigo) == term.value.upper()
    if term.kind == "marca":
        return normalized_text(T.p.marca) == normalized_text(literal(term.value))
    if term.kind == "ends_with":
        suffix = f"%{escape_like(term.value)}"

        def ends(column: Any) -> ColumnElement:
            return column.ilike(suffix, escape=LIKE_ESCAPE)

        return or_(ends(T.i.title), ends(T.p.descripcion), ends(T.p.marca), ends(T.p.codigo))
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


def erp_stock() -> ColumnElement:
    """The ERP stock of the row (depósito 1 on hand, `productos_erp.stock`, the figure Productos shows): only an
    item-level link in state `linked` gives the row a product, so a conflict, no product or a dangling link read
    NULL (unknown), never 0. A source apart from the ML stock (`ml_items` / `ml_user_product_stock`)."""
    return case((T.l.match_status == LINK_LINKED, T.p.stock), else_=None)


def stock_clauses() -> dict[str, ColumnElement]:
    # `full_sin_stock` is a real zero: a user product without a stock row has an unknown Full stock, not none.
    # `erp_sin_stock` likewise: a row without a linked product (unknown ERP stock) never matches.
    # `propio_sin_stock` is our own warehouse stock at ML (never the Full one, never the sum): a real zero too.
    return {
        "sin_stock": T.i.available_quantity == 0,
        "full_sin_stock": T.st.full_quantity == 0,
        "erp_sin_stock": erp_stock() <= 0,
        "erp_con_stock": erp_stock() > 0,
        "propio_sin_stock": T.st.own_quantity == 0,
    }


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


def _pm_group_in(group: str) -> ColumnElement:
    """`pm_grupo`: the rule of the tree's PM level (`ml_daily_metrics.groups.pm_pairs`, the very same subquery), so
    a PM node's filter selects exactly the publications the node counts."""
    pairs = pm_pairs("pm_group_pairs")
    owns = select(1).where(
        pairs.c.marca == func.upper(T.p.marca),
        pairs.c.categoria == func.upper(T.p.categoria),
    )
    if group == NO_GROUP:
        return ~exists(owns)
    return exists(owns.where(pairs.c.usuario_id == int(group)))


def _event(f: PublicationFilter) -> ColumnElement:
    where = [T.e.item_id == T.i.item_id, T.e.event_type.in_(f.event_types)]
    if f.event_since is not None:
        where.append(T.e.observed_at >= func.now() - literal(f.event_since, Interval))
    return exists(select(1).where(*where))


# --- Productos' "Filtros de Presencia" ----------------------------------------------------------------------------
#
# The params and meaning of `GET /productos` (`productos_listing.listar_productos`), as EXISTS over the row's linked
# product (`T.p`), so no join is added to the base select and nothing can multiply a row (a product has one
# `productos_pricing` row but may have several Tienda Nube variants). A product without a `productos_pricing` row
# reads "sin" like in Productos; a publication without a linked product has no product to ask, so it matches
# neither side. Mejor oferta is keyed by the MLA (`ofertas_ml`): the publication list asks it of each publication,
# the Producto view (`oferta_per_product`) of the product, any of its publications, as Productos does.


def product_pricing(name: str) -> Any:
    """Productos' pricing row of a product (`productos_pricing`) aliased `name`, for a view module that joins it
    itself (`stats`): the catalog models are named here only (`test_static_guards`)."""
    return aliased(ProductoPricing, name=name)


def _pricing_flag(flag: Any, on: bool) -> ColumnElement:
    pp = aliased(ProductoPricing, name="pp")
    flagged = exists(select(1).where(pp.item_id == T.p.item_id, flag(pp).is_(True)))
    return flagged if on else and_(T.p.item_id.isnot(None), ~flagged)


def _precio(on: bool) -> ColumnElement:
    pp = aliased(ProductoPricing, name="pp")
    priced = exists(select(1).where(pp.item_id == T.p.item_id, pp.precio_lista_ml.isnot(None)))
    return priced if on else and_(T.p.item_id.isnot(None), ~priced)


def _markup_sign(column: str, positive: bool) -> ColumnElement:
    """Productos' rule: positive is > 0, negative < 0; zero, NULL or no pricing row match neither side."""
    pp = aliased(ProductoPricing, name="pp")
    markup = getattr(pp, column)
    return exists(select(1).where(pp.item_id == T.p.item_id, markup > 0 if positive else markup < 0))


def _audited(f: PublicationFilter) -> ColumnElement:
    a = aliased(Auditoria, name="a")
    where = [a.item_id == T.p.item_id]
    if f.audit_users:
        where.append(a.usuario_id.in_(f.audit_users))
    if f.audit_kinds:
        # through the ORM column, which stores the member name the value maps to
        where.append(a.tipo_accion.in_([TipoAccion(kind) for kind in f.audit_kinds]))
    if f.audit_since is not None:
        where.append(a.fecha >= f.audit_since)
    if f.audit_until is not None:
        where.append(a.fecha <= f.audit_until)
    return exists(select(1).where(*where))


def current_offer(o: Any) -> list[ColumnElement]:
    return [o.fecha_desde <= func.current_date(), o.fecha_hasta >= func.current_date(), o.pvp_seller.isnot(None)]


def _oferta(on: bool, per_product: bool) -> ColumnElement:
    o = aliased(OfertaML, name="o")
    own = exists(select(1).where(o.mla == T.i.item_id, *current_offer(o)))
    if per_product:
        # any publication linked (item level) to the row's product; a row with no product has only itself
        sibling = aliased(MlItemProductLink, name="l_oferta")
        of_product = exists(
            select(1)
            .select_from(sibling)
            .join(o, o.mla == sibling.item_id)
            .where(
                sibling.variation_id == LINK_ITEM_LEVEL,
                sibling.producto_item_id == T.l.producto_item_id,
                *current_offer(o),
            )
        )
        has_product = T.l.producto_item_id.isnot(None)
        return or_(and_(has_product, of_product if on else ~of_product), and_(~has_product, own if on else ~own))
    return own if on else ~own


def _tienda_nube_in(state: str) -> ColumnElement:
    tn = aliased(TiendaNubeProducto, name="tn")
    active = select(1).where(tn.item_id == T.p.item_id, tn.activo.is_(True))
    if state == "con_descuento":
        return exists(active.where(tn.promotional_price > 0))
    if state == "sin_descuento":
        return exists(active.where(or_(tn.promotional_price.is_(None), tn.promotional_price == 0)))
    return and_(T.p.stock > 0, ~exists(active))


def presence_conditions(f: PublicationFilter) -> list[ColumnElement]:
    where = []
    if f.rebate is not None:
        where.append(_pricing_flag(lambda pp: pp.participa_rebate, f.rebate))
    if f.web_transf is not None:
        where.append(_pricing_flag(lambda pp: pp.participa_web_transferencia, f.web_transf))
    if f.out_of_cards is not None:
        where.append(_pricing_flag(lambda pp: pp.out_of_cards, f.out_of_cards))
    if f.tienda_nube is not None:
        where.append(_tienda_nube_in(f.tienda_nube))
    if f.oferta is not None:
        where.append(_oferta(f.oferta, f.oferta_per_product))
    if f.precio is not None:
        where.append(_precio(f.precio))
    if f.nuevos:
        where.append(T.p.fecha_sync >= func.now() - timedelta(days=7))
    where.extend(_markup_sign(column, positive) for column, positive in f.markup_signs)
    if f.audits:
        where.append(_audited(f))
    if f.mla_scope is not None:
        # one array parameter, as `_colors`: a promo scope can hold thousands of MLAs
        scope = literal(sorted(f.mla_scope), ARRAY(String))
        where.append(T.i.item_id == any_(scope) if f.mla_scope else false())
    return where


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
        where.append(T.l.producto_item_id == f.producto)
    if f.sin_producto:
        where.append(T.l.producto_item_id.is_(None))
    if f.pms:
        where.append(_pm(f))
    if f.pm_group is not None:
        where.append(_pm_group_in(f.pm_group))
    if f.family_id is not None:
        where.append(T.i.family_id == f.family_id)
    if f.listing and skip != "listing":
        where.append(_any_of(listing_clauses(), f.listing))
    if f.link and skip != "link":
        where.append(_link(f))
    if f.stock and skip != "stock":
        where.append(_any_of(stock_clauses(), f.stock))
    if f.event_types:
        where.append(_event(f))
    if f.colors or f.no_color:
        where.append(_colors(f))
    where.extend(presence_conditions(f))
    return where


def _colors(f: PublicationFilter) -> ColumnElement:
    if f.color_ids is None or f.colored_ids is None:
        raise RuntimeError("`colores` must be resolved (ml_publication_colors.resolve_color_filter) before the query")
    product = T.l.producto_item_id
    clauses = []
    if f.colors:
        clauses.append(product == any_(literal(list(f.color_ids), ARRAY(Integer))))
    if f.no_color:
        clauses.append(or_(product.is_(None), product != all_(literal(list(f.colored_ids), ARRAY(Integer)))))
    return or_(*clauses)


def build_base_select(f: PublicationFilter, *columns: Any, skip: Optional[str] = None) -> Select:
    """`SELECT <columns> FROM ml_items i LEFT JOIN ... WHERE <filter>`; no ORDER BY, no paging."""
    return select(*columns).select_from(joined()).where(*conditions(f, skip))
