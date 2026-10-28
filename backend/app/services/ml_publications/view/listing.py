"""The list of publications (design §3.1, §5.1): one row per MLA, filtered, sorted and paged, plus facets.

Statement count is constant for the size of the page: one COUNT, one page SELECT, and one statement per
page-level extra (variation counts, last event, store labels), however many rows the page holds (spec NFR-3).
Reads run under `SET LOCAL statement_timeout` (PgBouncer in transaction mode: LOCAL only, never session state).

Every ordering ends with `item_id`, so paging never repeats or skips a row (spec SRT-2).

Postgres only (`LATERAL` for the last event of each item, `FILTER` for the facet counters, `SET LOCAL`);
its tests are `@pytest.mark.postgres`.
"""

from __future__ import annotations

from dataclasses import dataclass, replace
from typing import Any, Mapping, Optional

from sqlalchemy import ARRAY, Text, and_, any_, case, cast, func, literal, select, text, true
from sqlalchemy.orm import Session

from app.models.marca_pm import MarcaPM
from app.models.ml_tienda_oficial import MlTiendaOficial
from app.models.tipo_cambio import TipoCambio
from app.services.ml_publications.links import DIVERGENCE_OTHER_PRODUCT, sku_key
from app.services.ml_publications.view.display import round_display
from app.services.ml_publications.view.filters import (
    AXES,
    FULFILLMENT,
    LINK_SKU_DIVERGENT,
    NO_STORE,
    FilterError,
    PublicationFilter,
    T,
    build_base_select,
    encode_key,
    erp_stock,
    link_divergence,
    link_state,
    listing_clauses,
    normalized_text,
    price_amount,
    status_value,
    stock_clauses,
)
from app.services.ml_publications.view.markup import PublicationMarkup
from app.services.ml_publications.view.markup_service import (
    ItemMarkup,
    MarkupQuery,
    MarkupResult,
    MarkupStats,
    compute_markups,
    product_markup,
)
from app.services.ml_publications.view.metrics_sort import METRIC_SORTS, needs_margin, ranked_page

STATEMENT_TIMEOUT = "8s"
SORT_ACTIVITY = "actividad"
SORT_MARKUP = "markup"  # not a column: the worst variation's markup, computed in Python (see `_list_by_markup`)
# sort key -> (expression of the first ordering column, descending by default)
SORT_COLUMNS: dict[str, tuple[Any, bool]] = {
    SORT_ACTIVITY: (lambda: T.i.last_trigger_received_at, True),
    "precio": (price_amount, False),
    "titulo": (lambda: func.lower(T.i.title), False),
    "stock_full": (lambda: T.st.full_quantity, True),
    "stock_propio": (lambda: T.st.own_quantity, True),
    "stock_erp": (erp_stock, True),
    "actualizado": (lambda: T.i.ml_last_updated, True),
    # the linked product's, as Productos sorts them; blank is no value, last like a missing product
    "codigo": (lambda: func.nullif(func.upper(T.p.codigo), ""), False),
    "marca": (lambda: func.nullif(normalized_text(T.p.marca), ""), False),
    "costo": (lambda: cost_in_pesos(), False),
}
MARGIN_SORTS = frozenset({"costo"})  # the cost is shown only with `ml_metricas.ver_ganancia`
DIRECTIONS = ("asc", "desc")
FACET_AXES = AXES
FACET_MAX_BRANDS = 100
DEFAULT_LIMIT = 50
MAX_LIMIT = 100


def cost_in_pesos() -> Any:
    """The linked product's cost in pesos: a USD cost at the latest USD rate (null without one), so USD 50 and
    ARS 60000 compare as money. Productos sorts the raw number, which puts every USD cost first."""
    latest_usd = (
        select(TipoCambio.venta)
        .where(TipoCambio.moneda == "USD")
        .order_by(TipoCambio.fecha.desc(), TipoCambio.id.desc())
        .limit(1)
        .scalar_subquery()
    )
    return case((T.p.moneda_costo == "USD", T.p.costo * latest_usd), else_=T.p.costo)


def unconverted_usd_cost() -> Any:
    """A USD cost `cost_in_pesos` has no rate for, in dollars (null otherwise): with no USD rate on record, the USD
    costs still sort, after the peso costs, by their own amount, and before the rows with no cost at all."""
    return case((and_(T.p.moneda_costo == "USD", cost_in_pesos().is_(None)), T.p.costo), else_=None)


# sort key -> the ordering column that breaks its ties, missing values last like the key's own
SORT_TIES: dict[str, Any] = {"costo": unconverted_usd_cost}


@dataclass(frozen=True)
class Sort:
    key: str
    descending: bool


@dataclass(frozen=True)
class ItemsPage:
    items: list[dict[str, Any]]
    total: int
    markup_stats: Optional[MarkupStats] = None
    ads_failed: bool = False  # the Ads provider raised while pricing this page: the figures are the plain markup


def parse_sort(orden: Optional[str], direction: Optional[str]) -> Sort:
    key = (orden or "").strip() or SORT_ACTIVITY
    known = [*SORT_COLUMNS, SORT_MARKUP, *METRIC_SORTS]
    if key not in known:
        raise FilterError("orden", f"unknown value {key!r}; known: {', '.join(known)}")
    wanted = (direction or "").strip().lower()
    if wanted and wanted not in DIRECTIONS:
        raise FilterError("dir", f"unknown value {wanted!r}; known: {', '.join(DIRECTIONS)}")
    if key in METRIC_SORTS:
        default_descending = True  # Métricas' figures: highest first, as Métricas orders them
    else:
        default_descending = False if key == SORT_MARKUP else SORT_COLUMNS[key][1]  # markup: the worst first
    return Sort(key, descending=(wanted == "desc") if wanted else default_descending)


def bound(db: Session, timeout: Optional[str] = None) -> None:
    """Bound the rest of the request's transaction in time (released by the commit or rollback that ends it); the
    list's own `STATEMENT_TIMEOUT` unless the caller (the detail) names a tighter one."""
    db.execute(text(f"SET LOCAL statement_timeout = '{timeout or STATEMENT_TIMEOUT}'"))


def resolve_pm_pairs(db: Session, f: PublicationFilter) -> PublicationFilter:
    """Fill `pm_pairs` from the PMs' (marca, categoria) assignments, trimmed and upper-cased like the tree keys them.

    Idempotent: a filter whose pairs are already resolved (or that has no `pms`) comes back as it is, with no
    query, so the router resolves once and `list_items` / `facets` may call it again safely."""
    if not f.pms or f.pm_pairs is not None:
        return f
    rows = (
        db.query(normalized_text(MarcaPM.marca), normalized_text(MarcaPM.categoria))
        .filter(MarcaPM.usuario_id.in_(f.pms), MarcaPM.marca.isnot(None), MarcaPM.categoria.isnot(None))
        .all()
    )
    pairs = {(marca, categoria) for marca, categoria in rows if marca and categoria}
    return replace(f, pm_pairs=tuple(sorted(pairs)))


def row_columns(*, cost: bool = False) -> list[Any]:
    i, sp, l, p, st = T.i, T.sp, T.l, T.p, T.st  # noqa: E741
    return [
        i.item_id,
        i.title,
        i.thumbnail,
        i.permalink,
        i.status,
        i.sub_status,
        i.listing_type_id,
        i.catalog_listing,
        i.logistic_type,
        i.official_store_id,
        i.brand.label("ml_brand"),
        i.family_id,
        i.family_name,
        i.user_product_id,
        i.seller_sku.label("sku_attribute"),
        i.seller_custom_field.label("sku_custom_field"),
        i.available_quantity,
        i.price.label("item_price"),
        i.last_trigger_received_at,
        i.gone_at,
        sp.amount.label("sale_amount"),
        sp.regular_amount,
        sp.promotion_type,
        sp.campaign_id,
        link_state().label("link_state"),
        l.producto_item_id,
        # the LINK's product: `T.p` also names a publication linked per variation only (`filters.primary_product`),
        # which has no item-level product, so its link shows none, as its `producto_item_id` and state do; the
        # product's cost only for who sees the margin: without it, not even selected
        *(
            case((l.producto_item_id.isnot(None), column), else_=None).label(column.key)
            for column in (p.codigo, p.descripcion, p.marca, *((p.costo, p.moneda_costo) if cost else ()))
        ),
        link_divergence().label("sku_divergence_kind"),
        l.suggested_producto_item_id,
        T.ps.codigo.label("suggested_codigo"),
        T.ps.descripcion.label("suggested_descripcion"),
        st.full_quantity,
        st.own_quantity,
        st.ml_last_updated.label("stock_as_of"),
        erp_stock().label("erp_quantity"),
    ]


def _order_by(sort: Sort) -> list[Any]:
    """The sort key and its tie-break, if any (missing values last in either direction), then `item_id`, which makes
    the order total."""
    keys = [SORT_COLUMNS[sort.key][0]()]
    if sort.key in SORT_TIES:
        keys.append(SORT_TIES[sort.key]())
    return [(key.desc() if sort.descending else key.asc()).nulls_last() for key in keys] + [T.i.item_id]


def _price(row: Any) -> dict[str, Any]:
    if row.sale_amount is not None:
        amount, source = row.sale_amount, "sale_price"
    elif row.item_price is not None:
        amount, source = row.item_price, "item_price"
    else:
        amount, source = None, None
    return {
        "amount": amount,
        "source": source,
        "regular_amount": row.regular_amount if source == "sale_price" else None,
        "promotion_type": row.promotion_type if source == "sale_price" else None,
        "campaign": row.campaign_id if source == "sale_price" else None,
        # ponytail: pricelist_id stays null: the list's markup block does not expose the list that prices the
        # row; the detail's breakdown (P8a) does
        "pricelist_id": None,
    }


def _seller_sku(row: Any) -> Optional[str]:
    """The publication's SKU: the automatic link's own key (`links.sku_key`), so the row shows what the rule reads."""
    return sku_key(row.sku_attribute, row.sku_custom_field)[0]


def _sku_divergence(row: Any) -> dict[str, Any] | None:
    """The product the publication's SKU names when it disagrees with the linked one (`links.sku_divergence`):
    none for `sin_coincidencia`, which names no single product (a stored suggested id is then stale and is not
    shown); the whole block is None when the SKU agrees."""
    if row.sku_divergence_kind is None:
        return None
    names_product = row.sku_divergence_kind == DIVERGENCE_OTHER_PRODUCT
    return {
        "kind": row.sku_divergence_kind,
        "producto_item_id": row.suggested_producto_item_id if names_product else None,
        "codigo": row.suggested_codigo if names_product else None,
        "descripcion": row.suggested_descripcion if names_product else None,
    }


def _item(row: Any, variations: dict[str, int], labels: dict[int, str], last_events: Optional[dict[str, Any]]) -> dict:
    item = {
        "item_id": row.item_id,
        "title": row.title,
        "thumbnail": row.thumbnail,
        "permalink": row.permalink,
        "status": row.status,
        "sub_status": list(row.sub_status or []),
        "listing_type_id": row.listing_type_id,
        "catalog_listing": row.catalog_listing,
        "logistic_type": row.logistic_type,
        "is_full": row.logistic_type == FULFILLMENT,
        "official_store_id": row.official_store_id,
        "store_label": labels.get(row.official_store_id),
        "ml_brand": row.ml_brand,
        "family_id": row.family_id,
        "family_name": row.family_name,
        "user_product_id": row.user_product_id,
        "seller_sku": _seller_sku(row),
        "variations_count": variations.get(row.item_id, 0),
        "gone": row.gone_at is not None or "deleted" in (row.sub_status or ()),  # filters.deleted(), per row
        "gone_at": row.gone_at,
        "price": _price(row),
        "stock": {
            "available": row.available_quantity,
            "full": row.full_quantity,
            "own": row.own_quantity,
            "as_of": row.stock_as_of,
        },
        "erp_stock": {"quantity": row.erp_quantity},  # the linked product's ERP stock, never merged with ML's
        "link": {
            "state": row.link_state,
            "producto_item_id": row.producto_item_id,
            "codigo": row.codigo,
            "descripcion": row.descripcion,
            "marca": row.marca,
        },
        "sku_divergence": _sku_divergence(row),
        "last_activity_at": row.last_trigger_received_at,
    }
    if last_events is not None:
        item["last_event"] = last_events.get(row.item_id)
    return item


def row_of(
    row: Any, *, variations_count: int, store_label: Optional[str], last_event: Optional[dict[str, Any]], events: bool
) -> dict[str, Any]:
    """The row of ONE publication from the columns of `row_columns()`, exactly as the list builds it (the detail's
    `row`); the page extras come already resolved. `last_event` only shows while `events` (the flag) is on."""
    labels = {row.official_store_id: store_label} if store_label is not None else {}
    last_events = {row.item_id: last_event} if events and last_event is not None else ({} if events else None)
    return _item(row, {row.item_id: variations_count}, labels, last_events)


def _variation_counts(db: Session, ids: list[str]) -> dict[str, int]:
    rows = db.execute(
        select(T.v.item_id, func.count()).where(T.v.item_id.in_(ids), T.v.gone_at.is_(None)).group_by(T.v.item_id)
    )
    return {item_id: count for item_id, count in rows}


def _store_labels(db: Session, ids: list[int]) -> dict[int, str]:
    if not ids:
        return {}
    rows = db.query(MlTiendaOficial.store_id, MlTiendaOficial.nombre).filter(MlTiendaOficial.store_id.in_(ids))
    return {store_id: nombre for store_id, nombre in rows}


def _last_events(db: Session, ids: list[str]) -> dict[str, dict[str, Any]]:
    """The newest event of each item (ties by id), one index probe per item: `DISTINCT ON` over the items' events
    read ALL of them to keep one, and the items that sort first by markup are often the busiest."""
    if not ids:
        return {}
    wanted = (
        func.unnest(literal(list(dict.fromkeys(ids)), ARRAY(Text)))
        .table_valued("item_id")
        .render_derived(name="wanted")
    )
    newest = (
        select(T.e.event_type, T.e.observed_at)
        .where(T.e.item_id == wanted.c.item_id)
        .order_by(T.e.observed_at.desc(), T.e.id.desc())
        .limit(1)
        .lateral("newest")
    )
    rows = db.execute(
        select(wanted.c.item_id, newest.c.event_type, newest.c.observed_at).select_from(wanted.join(newest, true()))
    )
    return {item_id: {"event_type": event_type, "observed_at": at} for item_id, event_type, at in rows}


def _assemble(db: Session, rows: list[Any], events: bool) -> list[dict[str, Any]]:
    """The page's row dicts: the page-level extras (variation counts, store labels, last events) in one statement
    each, however many rows there are."""
    ids = [row.item_id for row in rows]
    variations = _variation_counts(db, ids)
    labels = _store_labels(db, sorted({row.official_store_id for row in rows if row.official_store_id is not None}))
    last_events = _last_events(db, ids) if events else None
    return [_item(row, variations, labels, last_events) for row in rows]


def markup_out(item: ItemMarkup) -> dict[str, Any]:
    """The `markup` block of a row: range, worst variation, any-negative, why it has no value and how many
    variations are unpriced. Display values (2 decimals); sorting and filtering use the exact figures."""
    m = item.markup
    out: dict[str, Any] = {
        "min": round_display(m.value_min),
        "max": round_display(m.value_max),
        "worst": round_display(m.worst),
        "any_negative": m.any_negative,
        "reason": m.reason,
        "partial": m.partial,
    }
    if item.ads is not None:
        out["ads"] = {
            "state": item.ads.state,
            "amount": round_display(item.ads.amount),
            "units": item.ads.units,
            "per_unit": round_display(item.ads.per_unit),
        }
    return out


def _attach_markup(items: list[dict[str, Any]], computed: Mapping[str, ItemMarkup]) -> None:
    for item in items:
        if item["item_id"] in computed:
            item["markup"] = markup_out(computed[item["item_id"]])


def attach_cost(items: list[dict[str, Any]], rows: list[Any]) -> None:
    """Each row's linked product cost, as the panel shows it (only for who sees the margin, as the markup)."""
    for item, row in zip(items, rows):
        currency = getattr(row.moneda_costo, "value", row.moneda_costo)
        item["costo"] = None if row.costo is None else {"amount": row.costo, "currency": currency}


def _worst_first(computed: Mapping[str, ItemMarkup], descending: bool) -> list[str]:
    """Item ids by the worst variation's markup; publications without a value last in either direction, and
    `item_id` closes every tie so paging is stable."""
    priced = sorted(item_id for item_id, m in computed.items() if m.markup.worst is not None)
    priced.sort(key=lambda i: computed[i].markup.worst, reverse=descending)  # stable: ties stay by item_id
    unpriced = sorted(item_id for item_id, m in computed.items() if m.markup.worst is None)
    return priced + unpriced


def markup_accepted(db: Session, f: PublicationFilter, markup: MarkupQuery) -> tuple[MarkupResult, frozenset[str]]:
    """The markup filter, applied after the query: the WHOLE filtered set priced once (design §4.4) and the ids of
    the publications `markup.filter` accepts. The one definition of "what the markup filter keeps": the list
    (`_list_by_markup`) and the bulk actions' product resolver (`products.product_ids`) both call it."""
    result = compute_markups(db, markup.pricing_db, f=f, ads=markup.ads)

    def judged(item: ItemMarkup) -> PublicationMarkup:
        # one product asked (`producto=`, a product row or node): only the publication's units of that product, as
        # the Producto view and the tree's product nodes read them (`product_markup`)
        return product_markup(item, f.producto) if f.producto is not None else item.markup

    accepted = frozenset(
        item_id
        for item_id, item in result.items.items()
        if markup.filter.accepts((own := judged(item)).worst, own.any_negative)
    )
    return result, accepted


def _markup_ids(
    db: Session, f: PublicationFilter, sort: Sort, limit: Optional[int], offset: int, markup: MarkupQuery
) -> tuple[list[str], int, MarkupResult]:
    """The ids at `[offset, offset + limit)` (to the end when `limit` is None) of the set the markup filter keeps,
    in the requested order, its total and the set-wide markup. Sorting or filtering by markup needs the markup of the
    WHOLE filtered set (design §4.4): price it once and filter it in Python. The markup order is applied in Python
    too; a column order is applied by the database over the accepted ids only, which also cuts the page."""
    result, kept = markup_accepted(db, f, markup)
    if sort.key == SORT_MARKUP:
        wanted = [item_id for item_id in _worst_first(result.items, sort.descending) if item_id in kept]
        end = None if limit is None else offset + limit
        return wanted[offset:end], len(wanted), result
    # The database orders only the publications the markup filter accepted and cuts the page: it used to order
    # the whole filtered set and ship every id back just to keep fifty.
    accepted = [item_id for item_id in result.items if item_id in kept]  # the computed order, as before
    total = len(accepted)
    if offset >= total:
        return [], total, result
    only_accepted = build_base_select(f, T.i.item_id).where(T.i.item_id == any_(literal(accepted, ARRAY(Text))))
    if sort.key in METRIC_SORTS:
        return ranked_page(db, only_accepted, sort.key, sort.descending, limit, offset), total, result
    page = db.execute(only_accepted.order_by(*_order_by(sort)).limit(limit).offset(offset)).scalars()
    return list(page), total, result


def _rows_for_ids(db: Session, f: PublicationFilter, ids: list[str], *, cost: bool = False) -> list[Any]:
    """The `row_columns()` of `ids` that still match `f`, in the order of `ids` (one statement)."""
    if not ids:
        return []
    found = db.execute(
        build_base_select(f, *row_columns(cost=cost)).where(T.i.item_id == any_(literal(ids, ARRAY(Text))))
    )
    by_id = {row.item_id: row for row in found}
    return [by_id[i] for i in ids if i in by_id]


def _list_by_markup(
    db: Session, f: PublicationFilter, sort: Sort, limit: int, offset: int, events: bool, markup: MarkupQuery
) -> ItemsPage:
    """The page of a markup sort or filter (`_markup_ids`), then only the page's rows (by id), with the markup
    computed for the whole set. A fixed number of statements."""
    page_ids, total, result = _markup_ids(db, f, sort, limit, offset, markup)
    if not page_ids:
        return ItemsPage([], total, result.stats, result.ads_failed)
    rows = _rows_for_ids(db, f, page_ids, cost=True)
    items = _assemble(db, rows, events)
    _attach_markup(items, result.items)
    attach_cost(items, rows)
    return ItemsPage(items, total, result.stats, result.ads_failed)


def _check(f: PublicationFilter, sort: Sort, events: bool, can_see_margin: bool) -> None:
    if f.needs_events and not events:
        raise FilterError("evento", "requires the events flag (events.enabled) to be on")
    if sort.key in METRIC_SORTS and needs_margin(sort.key) and not can_see_margin:
        raise FilterError("orden", f"{sort.key} requires the ml_metricas.ver_ganancia permission")
    if sort.key in MARGIN_SORTS and not can_see_margin:
        raise FilterError("orden", f"{sort.key} requires the ml_metricas.ver_ganancia permission")


def _by_markup(sort: Sort, markup: Optional[MarkupQuery]) -> bool:
    """Whether the order (or the selection) is the markup's, computed in Python over the whole set."""
    if markup is not None and (sort.key == SORT_MARKUP or markup.filter.active):
        return True
    if sort.key == SORT_MARKUP:
        raise FilterError("orden", "markup requires the ml_metricas.ver_ganancia permission")
    return False


def list_items(
    db: Session,
    f: PublicationFilter,
    sort: Sort,
    limit: int,
    offset: int,
    *,
    events: bool,
    markup: Optional[MarkupQuery] = None,
    can_see_margin: bool = False,
) -> ItemsPage:
    """One page of publications. `events` is the `events.enabled` flag: the event filter needs it and the last
    event is only read while it is on. `markup` (the caller may see margins) adds each row's markup; sorting by
    it or filtering on it prices the whole filtered set first. A Métricas sort (`METRIC_SORTS`) ranks the whole
    filtered set by the Board's figures; the margin ones need `can_see_margin` (fail closed: it defaults to no)."""
    _check(f, sort, events, can_see_margin)
    f = resolve_pm_pairs(db, f)
    if _by_markup(sort, markup):
        return _list_by_markup(db, f, sort, limit, offset, events, markup)
    total = db.execute(build_base_select(f, func.count())).scalar_one()
    if total == 0 or offset >= total:
        return ItemsPage([], total, None if markup is None else MarkupStats(0, {}, 0.0))
    if sort.key in METRIC_SORTS:
        page_ids = ranked_page(db, build_base_select(f, T.i.item_id), sort.key, sort.descending, limit, offset)
        rows = _rows_for_ids(db, f, page_ids, cost=markup is not None)
    else:
        rows = db.execute(
            build_base_select(f, *row_columns(cost=markup is not None))
            .order_by(*_order_by(sort))
            .limit(limit)
            .offset(offset)
        ).all()
    items = _assemble(db, rows, events)
    if markup is None:
        return ItemsPage(items, total)
    result = compute_markups(db, markup.pricing_db, item_ids=[row.item_id for row in rows], ads=markup.ads)
    _attach_markup(items, result.items)
    attach_cost(items, rows)
    return ItemsPage(items, total, result.stats, result.ads_failed)


def ordered_keys(
    db: Session,
    f: PublicationFilter,
    sort: Sort,
    cap: Optional[int],
    *,
    events: bool,
    markup: Optional[MarkupQuery] = None,
    can_see_margin: bool = False,
) -> list[str]:
    """The item ids of the WHOLE filtered set, at most `cap` (every one when None), in the very order `list_items`
    pages them (the markup sort and filter included, through the same `_markup_ids`): the keys an export fixes before
    reading its pages."""
    _check(f, sort, events, can_see_margin)
    f = resolve_pm_pairs(db, f)
    if _by_markup(sort, markup):
        return _markup_ids(db, f, sort, cap, 0, markup)[0]
    if sort.key in METRIC_SORTS:
        return ranked_page(db, build_base_select(f, T.i.item_id), sort.key, sort.descending, cap, 0)
    return list(db.execute(build_base_select(f, T.i.item_id).order_by(*_order_by(sort)).limit(cap)).scalars())


def items_for_keys(
    db: Session, f: PublicationFilter, ids: list[str], *, events: bool, markup: Optional[MarkupQuery] = None
) -> ItemsPage:
    """The rows of `ids` in their order, built as `list_items` builds them, each with its markup (priced for these
    ids) when `markup` is given. A key whose row stopped matching `f` is skipped. The markup FILTER is not applied
    again: the keys already passed it."""
    f = resolve_pm_pairs(db, f)
    rows = _rows_for_ids(db, f, list(ids), cost=markup is not None)
    if not rows:
        return ItemsPage([], 0)
    items = _assemble(db, rows, events)
    if markup is None:
        return ItemsPage(items, len(items))
    result = compute_markups(db, markup.pricing_db, item_ids=[row.item_id for row in rows], ads=markup.ads)
    _attach_markup(items, result.items)
    attach_cost(items, rows)
    return ItemsPage(items, len(items), result.stats, result.ads_failed)


def _grouped(
    db: Session, f: PublicationFilter, axis: str, key: Any, *, present: bool = False, limit: Optional[int] = None
) -> dict:
    """`key -> rows` over the base select without `axis`' own selection, biggest first. `present` drops NULL keys."""
    count = func.count()
    query = build_base_select(f, key, count.label("n"), skip=axis)
    if present:
        query = query.where(key.isnot(None))
    query = query.group_by(key).order_by(count.desc(), key)
    rows = db.execute(query.limit(limit) if limit else query)
    return {name: count for name, count in rows}


def _flags(db: Session, f: PublicationFilter, axis: str, clauses: dict) -> dict[str, int]:
    counts = [func.count().filter(clause).label(name) for name, clause in clauses.items()]
    return dict(db.execute(build_base_select(f, *counts, skip=axis)).one()._mapping)


def _link_counts(db: Session, f: PublicationFilter) -> dict[str, int]:
    """The link axis: one count per link state, plus `sku_divergente` (a subset of `auto`, counted in the same
    statement) when any row diverges. Like the states, a value with no rows is not offered."""
    state, count = link_state(), func.count()
    divergent = func.count().filter(link_divergence().isnot(None))
    query = build_base_select(f, state, count.label("n"), divergent.label("d"), skip="link")
    rows = db.execute(query.group_by(state).order_by(count.desc(), state)).all()
    counts = {name: n for name, n, _ in rows}
    divergent_total = sum(d for _, _, d in rows)
    return {**counts, LINK_SKU_DIVERGENT: divergent_total} if divergent_total else counts


def facets(db: Session, f: PublicationFilter) -> dict[str, dict[str, int]]:
    """Counts per value of each facet axis: one grouped COUNT per axis over the base select, each axis with its
    own selection left out (so choosing a value never makes its siblings read zero). The brand values are keys as
    the tree writes them (`encode_key`): a screen shows the decoded name and sends the key back unchanged."""
    f = resolve_pm_pairs(db, f)
    brand = func.nullif(normalized_text(T.p.marca), "")  # as the tree keys a brand; none (blank) is not offered
    by_status = _grouped(db, f, "status", status_value())
    by_store = _grouped(db, f, "stores", func.coalesce(cast(T.i.official_store_id, Text), NO_STORE))
    by_brand = _grouped(db, f, "marcas", brand, present=True, limit=FACET_MAX_BRANDS)
    return {
        "status": by_status,
        "stores": by_store,
        "marcas": {encode_key(name): count for name, count in by_brand.items()},
        "listing": _flags(db, f, "listing", listing_clauses()),
        "link": _link_counts(db, f),
        "stock": _flags(db, f, "stock", stock_clauses()),
    }
