"""The Resumen of one publication: ALL its data in one read (design §3.3, addendum decision 2).

What the panel shows, and where each piece comes from (a constant number of statements, whatever the variations):

1. the item, in ONE statement over the list's own joins (`filters.joined`) plus the replenishment, the store name and
   the live-variation count: the list `row` (built by `listing.row_of`, so it equals the list's byte for byte), every
   `ml_items` column but `raw` and its hash (`item`), a whitelisted subset of `raw` (`extra`), the per-location stock
   and the replenishment state;
2. the last event, only while `events.enabled` (the list's own rule);
3. the links of ALL units with the linked products (this is why the module names the product catalog, see
   `test_static_guards.py`): the item-level product with its categories and list prices, and its cost only for a
   caller who may see margins (the cost columns are not even selected otherwise);
4. the freshness of every sub-resource that applies, in one `UNION ALL` by primary key;
5. with margins: `markup_service.compute_detail` (the three statements of the markup inputs and one shipping batch),
   whose breakdown is the very `unit_markup` pipeline of the list.

The variations are NOT here: they have their own endpoint (`variations.py`, P6c). Nothing here writes, and no
text is ordered or compared by the database (links are ordered by variation id, freshness by a fixed list), so the
result does not depend on the collation of the server.
"""

from __future__ import annotations

from decimal import Decimal
from typing import Any, Mapping, Optional

from sqlalchemy import func, select, text
from sqlalchemy.orm import Session, aliased, join as orm_join
from sqlalchemy.sql import Select

from app.models.comision_config import SubcategoriaGrupo
from app.models.ml_publications import MlItem, MlItemProductLink, MlUserProductReplenishment
from app.models.ml_tienda_oficial import MlTiendaOficial
from app.models.producto import ProductoERP, ProductoPricing
from app.services.ml_publications.view import listing, markup_service
from app.services.ml_publications.view.filters import FULFILLMENT, LINK_ITEM_LEVEL, LINK_LINKED, T, joined
from app.services.ml_publications.view.markup_service import MarkupQuery
from app.services.ml_publications.view.variations import link_state_of
from app.services.pricing_columns import PRICELIST_TO_CAMPO

STATEMENT_TIMEOUT = "3s"
# Not shown: the whole body (a whitelisted part of it is) and its hash, which is bytes with no meaning to a person.
HIDDEN_COLUMNS = frozenset({"raw", "raw_hash"})

# State tables of the resources the panel reports, by key: item id, user product id, family id.
ITEM_KEYED = {
    "description": "ml_item_descriptions",
    "prices": "ml_item_prices",
    "sale_price": "ml_item_sale_prices",
    "promotions": "ml_item_seller_promotions",
    "competition": "ml_item_competition",
    "moderation": "ml_item_moderations",
    "performance": "ml_item_performance",
    "visits": "ml_item_visits",
}
USER_PRODUCT_KEYED = {"user_product": "ml_user_products", "stock": "ml_user_product_stock"}
FAMILY_KEYED = {"family": "ml_user_product_families"}
RESOURCE_ORDER = (
    "items",
    *ITEM_KEYED,
    "user_product",
    "stock",
    "family",
    "replenishment",
)

STATE_OK = "ok"
STATE_NOT_FOUND = "not_found"
STATE_ERROR = "error"
STATE_NEVER_FETCHED = "never_fetched"
STATE_GONE = "gone"
STATE_PARTIAL = "partial"
NOT_FOUND_STATUS = 404

# The part of the item body (`raw`) the panel shows, sampled from the captured items (`items_bulk_*`, 10 items):
# the scalar fields, then the structures reduced to the keys a person reads. Whatever else the body carries
# (`seller_contact`, `location`, `geolocation`, the street of `seller_address`, ...) is not shown.
SCALAR_EXTRAS = (
    "warranty",
    "listing_source",
    "automatic_relist",
    "accepts_mercadopago",
    "international_delivery_mode",
    "video_id",
    "thumbnail_id",
    "differential_pricing",
)
LIST_EXTRAS = ("channels", "deal_ids")
SHIPPING_KEYS = ("mode", "local_pick_up", "store_pick_up", "tags")
OBJECT_LISTS: dict[str, tuple[str, ...]] = {
    "sale_terms": ("id", "name", "value_name"),
    "attributes": ("id", "name", "value_name"),
    "item_relations": ("id", "variation_id", "stock_relation"),
    "pictures": ("id", "secure_url", "size", "max_size"),
}
EXTRA_FIELDS = (*SCALAR_EXTRAS, *LIST_EXTRAS, "shipping", *OBJECT_LISTS, "seller_address")

ITEM_COLUMNS = [column.key for column in MlItem.__table__.columns if column.key not in HIDDEN_COLUMNS]
REPLENISHMENT_COLUMNS = (
    "partial",
    "content_missing",
    "period",
    "units_30d",
    "gmv_30d",
    "currency_id",
    "units_7d",
    "units_14d",
    "units_21d",
    "days_out_of_stock_21d",
    "history_through",
    "total_stock",
    "shipping_urgency",
    "minimum_distributable_stock",
    "http_status",
    "never_existed",
    "fetched_at",
    "last_checked_at",
)


def bound(db: Session) -> None:
    """Bound the rest of the request's transaction in time (released by the commit or rollback that ends it)."""
    db.execute(text(f"SET LOCAL statement_timeout = '{STATEMENT_TIMEOUT}'"))


# ── pure helpers ─────────────────────────────────────────────────


def _plain(value: Any) -> Any:
    return float(value) if isinstance(value, Decimal) else value


def _round(value: Optional[float]) -> Optional[float]:
    return None if value is None else round(float(value), 2)


def _pick(source: Any, keys: tuple[str, ...]) -> Optional[dict[str, Any]]:
    return {key: source.get(key) for key in keys} if isinstance(source, Mapping) else None


def _name_of(place: Any) -> Optional[str]:
    return place.get("name") if isinstance(place, Mapping) else None


def extra_fields(raw: Any) -> dict[str, Any]:
    """The whitelisted part of an item body; every field is present, `None` when the body lacks it or it is not of
    the captured shape (never a guess)."""
    body = raw if isinstance(raw, Mapping) else {}
    out: dict[str, Any] = {name: None for name in EXTRA_FIELDS}
    for name in SCALAR_EXTRAS:
        out[name] = body.get(name)
    for name in LIST_EXTRAS:
        out[name] = list(body[name]) if isinstance(body.get(name), list) else None
    shipping = _pick(body.get("shipping"), SHIPPING_KEYS)
    out["shipping"] = shipping
    for name, keys in OBJECT_LISTS.items():
        entries = body.get(name)
        if isinstance(entries, list):
            out[name] = [_pick(entry, keys) for entry in entries if isinstance(entry, Mapping)]
    address = body.get("seller_address")
    if isinstance(address, Mapping):
        out["seller_address"] = {"city": _name_of(address.get("city")), "state": _name_of(address.get("state"))}
    return out


def locations_of(raw_locations: Any) -> Optional[list[dict[str, Any]]]:
    """`[{type, quantity}]` of the stock body, or `None` (unknown, not "empty") when it carries no list of them.
    An entry that is not an object with a text type and an integer quantity is skipped."""
    if not isinstance(raw_locations, list):
        return None
    return [
        {"type": entry["type"], "quantity": entry["quantity"]}
        for entry in raw_locations
        if isinstance(entry, Mapping)
        and isinstance(entry.get("type"), str)
        and isinstance(entry.get("quantity"), int)
        and not isinstance(entry.get("quantity"), bool)
    ]


def state_of(http_status: Optional[int], never_existed: Optional[bool]) -> str:
    """The state of a stored sub-resource from its last answer: nothing yet, ok (2xx), not found (404 or an id ML
    says never existed) or any other failure."""
    if http_status is None:
        return STATE_NEVER_FETCHED
    if 200 <= http_status < 300:
        return STATE_OK
    if http_status == NOT_FOUND_STATUS or never_existed:
        return STATE_NOT_FOUND
    return STATE_ERROR


def _freshness_entry(
    resource: str,
    http_status: Optional[int],
    never_existed: Optional[bool],
    fetched_at: Any,
    last_checked_at: Any,
    *,
    gone: bool = False,
) -> dict[str, Any]:
    state = STATE_GONE if gone else state_of(http_status, never_existed)
    return {
        "resource": resource,
        "state": state,
        "fetched_at": fetched_at,
        "last_checked_at": last_checked_at,
        "http_status": http_status,
    }


def replenishment_of(row: Any, is_full: bool) -> Optional[dict[str, Any]]:
    """Replenishment of a Full publication: `ok`, `partial` (a 206), `not_found`, `error` or `never_fetched` (no
    answer stored yet). `None` when the publication is not Full: it has no replenishment to report."""
    if not is_full:
        return None
    shown = {
        "content_missing": None,
        "period": None,
        "units_30d": None,
        "gmv_30d": None,
        "currency": None,
        "units_7d": None,
        "units_14d": None,
        "units_21d": None,
        "days_out_of_stock_21d": None,
        "shipping_urgency": None,
        "total_stock": None,
        "minimum_distributable_stock": None,
        "history_through": None,
        "fetched_at": None,
    }
    state = state_of(row.r_http_status, row.r_never_existed) if row.r_key is not None else STATE_NEVER_FETCHED
    if state == STATE_NEVER_FETCHED:
        return {"status": STATE_NEVER_FETCHED, **shown}
    for name in shown:
        shown[name] = _plain(getattr(row, "r_currency_id" if name == "currency" else f"r_{name}"))
    status = STATE_PARTIAL if state == STATE_OK and row.r_partial else state
    return {"status": status, **shown}


# ── statements ───────────────────────────────────────────────────


def _last_event_columns(item_id: str) -> list[Any]:
    """The newest event of the item (type and time) as two scalar subqueries of the item statement: the list's order
    (`observed_at DESC, id DESC`), no statement of its own."""
    newest = (T.e.observed_at.desc(), T.e.id.desc())
    return [
        select(T.e.event_type)
        .where(T.e.item_id == item_id)
        .order_by(*newest)
        .limit(1)
        .scalar_subquery()
        .label("le_type"),
        select(T.e.observed_at)
        .where(T.e.item_id == item_id)
        .order_by(*newest)
        .limit(1)
        .scalar_subquery()
        .label("le_at"),
    ]


def _item_select(item_id: str, events: bool = False) -> Select:
    """The one statement of the item: the list's row columns and the extras, over the list's joins."""
    replenishment = aliased(MlUserProductReplenishment, name="rp")
    store = aliased(MlTiendaOficial, name="so")
    live_variations = select(func.count()).where(T.v.item_id == T.i.item_id, T.v.gone_at.is_(None)).scalar_subquery()
    source = joined().outerjoin(replenishment, replenishment.user_product_id == T.i.user_product_id)
    source = source.outerjoin(store, store.store_id == T.i.official_store_id)
    columns = [
        *listing.row_columns(),
        live_variations.label("variations_count"),
        store.nombre.label("store_label"),
        *(getattr(T.i, name).label(f"x_{name}") for name in ITEM_COLUMNS),
        T.i.raw.label("raw_body"),
        T.st.raw["locations"].label("stock_locations"),
        replenishment.user_product_id.label("r_key"),
        *(getattr(replenishment, name).label(f"r_{name}") for name in REPLENISHMENT_COLUMNS),
        *(_last_event_columns(item_id) if events else []),
    ]
    return select(*columns).select_from(source).where(T.i.item_id == item_id, T.i.never_existed.isnot(True))


def _links_select(item_id: str, margin: bool) -> Select:
    """Every link of the publication with its product, categories and list prices; the cost columns only with
    `margin` (they are not selected otherwise, so they cannot reach the response)."""
    link, product, pricing, names = MlItemProductLink, ProductoERP, ProductoPricing, SubcategoriaGrupo
    joins = orm_join(
        orm_join(
            orm_join(link, product, product.item_id == link.producto_item_id, isouter=True),
            pricing,
            pricing.item_id == product.item_id,
            isouter=True,
        ),
        names,
        names.subcat_id == product.subcategoria_id,
        isouter=True,
    )
    columns = [
        link.variation_id,
        link.source,
        link.match_status,
        link.producto_item_id,
        link.matched_sku,
        link.sku_field,
        link.suggested_producto_item_id,
        link.suggestion_status,
        link.linked_at,
        link.note,
        product.item_id.label("product_id"),
        product.codigo,
        product.descripcion,
        product.marca,
        product.categoria,
        product.subcategoria_id,
        names.nombre_subcategoria,
        *(getattr(pricing, campo).label(campo) for campo in PRICELIST_TO_CAMPO.values()),
    ]
    if margin:
        columns += [product.costo, product.moneda_costo, product.iva]
    return select(*columns).select_from(joins).where(link.item_id == item_id).order_by(link.variation_id)


def _link_out(row: Any) -> dict[str, Any]:
    return {
        "variation_id": row.variation_id,
        "state": link_state_of(row.match_status, row.source),
        "source": row.source,
        "match_status": row.match_status,
        "producto_item_id": row.producto_item_id,
        "codigo": row.codigo,
        "descripcion": row.descripcion,
        "marca": row.marca,
        "matched_sku": row.matched_sku,
        "sku_field": row.sku_field,
        "suggested_producto_item_id": row.suggested_producto_item_id,
        "suggestion_status": row.suggestion_status,
        "linked_at": row.linked_at,
        "note": row.note,
    }


def _product_out(row: Any, margin: bool) -> dict[str, Any]:
    out: dict[str, Any] = {
        "item_id": row.product_id,
        "codigo": row.codigo,
        "descripcion": row.descripcion,
        "marca": row.marca,
        "categoria": row.categoria,
        "subcategoria_id": row.subcategoria_id,
        "subcategoria": row.nombre_subcategoria,
        "precios_lista": {
            str(pricelist_id): _round(getattr(row, campo)) for pricelist_id, campo in PRICELIST_TO_CAMPO.items()
        },
    }
    if margin:
        currency = getattr(row.moneda_costo, "value", row.moneda_costo)
        out.update({"costo": row.costo, "moneda_costo": currency, "iva": row.iva})
    return out


def _freshness_sql(item_id: str, user_product_id: Optional[str], family_id: Optional[int]) -> tuple[Any, dict]:
    """One `UNION ALL` of primary-key reads over the state tables that apply to this publication."""
    columns = "http_status, never_existed, fetched_at, last_checked_at"
    parts, params = [], {"item_id": item_id}
    for resource, table in ITEM_KEYED.items():
        parts.append(f"SELECT '{resource}' AS resource, {columns} FROM {table} WHERE item_id = :item_id")
    if user_product_id is not None:
        params["user_product_id"] = user_product_id
        for resource, table in USER_PRODUCT_KEYED.items():
            parts.append(
                f"SELECT '{resource}' AS resource, {columns} FROM {table} WHERE user_product_id = :user_product_id"
            )
    if family_id is not None:
        params["family_id"] = family_id
        for resource, table in FAMILY_KEYED.items():
            parts.append(f"SELECT '{resource}' AS resource, {columns} FROM {table} WHERE family_id = :family_id")
    return text(" UNION ALL ".join(parts)), params


def _freshness(db: Session, row: Any, is_full: bool) -> list[dict[str, Any]]:
    statement, params = _freshness_sql(row.item_id, row.x_user_product_id, row.x_family_id)
    stored = {r.resource: r for r in db.execute(statement, params)}
    entries = {
        "items": _freshness_entry(
            "items",
            row.x_http_status,
            row.x_never_existed,
            row.x_fetched_at,
            row.x_last_checked_at,
            gone=row.x_gone_at is not None,
        )
    }
    applicable = [*ITEM_KEYED]
    if row.x_user_product_id is not None:
        applicable += USER_PRODUCT_KEYED
    if row.x_family_id is not None:
        applicable += FAMILY_KEYED
    for resource in applicable:
        found = stored.get(resource)
        entries[resource] = (
            _freshness_entry(resource, None, None, None, None)
            if found is None
            else _freshness_entry(
                resource, found.http_status, found.never_existed, found.fetched_at, found.last_checked_at
            )
        )
    if is_full:
        entries["replenishment"] = (
            _freshness_entry("replenishment", None, None, None, None)
            if row.r_key is None
            else _freshness_entry(
                "replenishment", row.r_http_status, row.r_never_existed, row.r_fetched_at, row.r_last_checked_at
            )
        )
    return [entries[resource] for resource in RESOURCE_ORDER if resource in entries]


def _breakdown_out(found: markup_service.DetailMarkup) -> Optional[dict[str, Any]]:
    b = found.breakdown
    if b is None:
        return None
    return {
        "variation_id": found.variation_id,
        "price": _round(b.price),
        "price_source": b.price_source,
        "pricelist_id": b.pricelist_id,
        "installments": b.installments,
        "comision_pct": _round(b.comision_pct),
        "comision_total": _round(b.comision_total),
        "costo_envio": _round(b.costo_envio),
        "envio_source": b.envio_source,
        "limpio": _round(b.limpio),
        "costo_ars": _round(b.costo_ars),
        "markup": _round(b.markup),
    }


# ── entry point ──────────────────────────────────────────────────


def get_detail(db: Session, item_id: str, *, events: bool, markup: Optional[MarkupQuery] = None) -> Optional[dict]:
    """The detail of `item_id`, or `None` when it is not in the store. `events` is the `events.enabled` flag.
    `markup` (its presence means the caller may see margins) adds the cost of the product, the row's markup and the
    breakdown of the worst unit. `can_resync` is the router's: it is a permission, not data."""
    bound(db)
    row = db.connection().execute(_item_select(item_id, events)).first()
    if row is None:
        return None
    margin = markup is not None
    is_full = row.logistic_type == FULFILLMENT
    last_event = {"event_type": row.le_type, "observed_at": row.le_at} if events and row.le_type is not None else None
    out_row = listing.row_of(
        row, variations_count=row.variations_count, store_label=row.store_label, last_event=last_event, events=events
    )
    links = list(db.connection().execute(_links_select(item_id, margin)).all())
    item_level = next((r for r in links if r.variation_id == LINK_ITEM_LEVEL), None)
    has_product = (
        item_level is not None and item_level.match_status == LINK_LINKED and item_level.product_id is not None
    )
    freshness = _freshness(db, row, is_full)

    body: dict[str, Any] = {
        "row": out_row,
        "item": {name: _plain(getattr(row, f"x_{name}")) for name in ITEM_COLUMNS},
        "extra": extra_fields(row.raw_body),
        "sub_status": list(row.x_sub_status or []),
        "tags": list(row.x_tags or []),
        "health": _plain(row.x_health),
        "condition": row.x_condition,
        "date_created": row.x_date_created,
        "ml_last_updated": row.x_ml_last_updated,
        "fetched_at": row.x_fetched_at,
        "stock_locations": locations_of(row.stock_locations),
        "stock_as_of": row.stock_as_of,
        "replenishment": replenishment_of(row, is_full),
        "links": [_link_out(r) for r in links],
        "product": _product_out(item_level, margin) if has_product else None,
        "freshness": freshness,
    }
    if margin:
        found = markup_service.compute_detail(db, markup.pricing_db, item_id)
        if found is not None:
            out_row["markup"] = listing.markup_out(found.item)
        body["markup_breakdown"] = None if found is None else _breakdown_out(found)
    return body
