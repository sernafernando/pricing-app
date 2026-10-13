"""The markup INPUTS of a set of publications (design §4.3, §4.4): extracted in three statements (four when some
unit has no price of its own), whatever the size.

SQL only extracts; the maths is `markup.unit_markup` (P2). For each publication the statements read:

1. the item: listing type, tags, the price inputs (current sale price and `ml_items.price`) and the installments
   campaign sale term, which is read ONLY when no campaign tag is present (the tag wins, see `pricelist_resolver`);
2. its live variations;
3. every `linked` unit (item level and per variation) with the linked product's cost fields;
4. only when some unit has no usable price (neither the sale price nor `ml_items.price`): the Productos list prices
   its fallback reads, for the products of those units. The big statements do not carry them.

The set is either explicit ids (a page) or a `PublicationFilter` (the whole filtered set, for sorting and
filtering by markup). Statements 2 and 3 are scoped by the ids statement 1 returned, bound as ONE JSON text
parameter (unnested by the server), so the filter's joins run once and neither the statement text nor the cost of
binding grows with the set.

This module is the second view module allowed to name the product catalog (see `test_static_guards.py`): it reads
the cost fields of the products a publication is linked to, in one join from the stored links, and never writes.
"""

from __future__ import annotations

import json
from dataclasses import dataclass
from types import MappingProxyType
from typing import Any, Mapping, Optional, Sequence

from sqlalchemy import ARRAY, Integer, Text, and_, case, cast, func, literal, literal_column, select, type_coerce
from sqlalchemy.dialects.postgresql import JSONB, JSONPATH
from sqlalchemy.orm import Session, aliased, join as orm_join
from sqlalchemy.types import NullType

from app.models.ml_publications import MlItem, MlItemProductLink, MlItemSalePrice, MlItemVariation
from app.models.producto import ProductoERP, ProductoPricing
from app.services.ml_publications.pricelist_resolver import CAMPAIGN_TAGS
from app.services.ml_publications.view.filters import (
    LINK_ITEM_LEVEL,
    LINK_LINKED,
    PublicationFilter,
    build_base_select,
    T,
)
from app.services.ml_publications.view.markup import UnitInputs
from app.services.pricing_columns import PRICELIST_TO_CAMPO

# The installments campaign of an item that carries no campaign tag: the `INSTALLMENTS_CAMPAIGN` sale term.
CAMPAIGN_SALE_TERM = '$.sale_terms[*] ? (@.id == "INSTALLMENTS_CAMPAIGN").value_name'
FALLBACK_COLUMNS = tuple(PRICELIST_TO_CAMPO.values())
DEFAULT_IVA = 21.0
_NO_PRICES: Mapping[str, Optional[float]] = MappingProxyType({})  # a unit with a price of its own


@dataclass(frozen=True)
class PublicationInputs:
    """Everything needed to price one publication: its item-level unit and one entry per live variation
    (`None` when that variation has no link of its own; the fallback to the item-level unit is `markup`'s).
    `variation_ids` names the variation of each entry of `variation_units`, in the same order."""

    item_id: str
    item_unit: UnitInputs
    variation_units: tuple[Optional[UnitInputs], ...]
    variation_ids: tuple[int, ...] = ()


def _unnested(ids: Sequence[Any]) -> Any:
    return func.jsonb_array_elements_text(cast(literal(json.dumps(list(ids))), JSONB)).column_valued()


def _ids_param(ids: Sequence[str]) -> Any:
    """The ids as ONE JSON text parameter, unnested server side. Bound as an array of N text elements the driver
    quotes and the server parses N literals (about 50 ms for 40k ids, per statement); as one JSON text it is about
    7 ms, and the statement text does not change with N either."""
    return select(_unnested(ids))


def _campaign(item: Any) -> Any:
    """The sale-term campaign, evaluated only when no campaign tag is present."""
    term = func.jsonb_path_query_first(item.raw, cast(literal(CAMPAIGN_SALE_TERM), JSONPATH)).op("#>>")(
        literal_column("'{}'")
    )
    return case((func.coalesce(item.tags, literal([], ARRAY(Text))).overlap(list(CAMPAIGN_TAGS)), None), else_=term)


def _tags(item: Any) -> Any:
    """`tags` as the driver returns them (a list), skipping SQLAlchemy's per-element array processor: it costs
    more than the whole fetch on a 25k-row set and the elements are already plain strings."""
    return type_coerce(item.tags, NullType()).label("tags")


def _floats(value: Any) -> Optional[float]:
    return None if value is None else float(value)


def _product_columns(product: Any) -> list[Any]:
    """The cost fields of a linked product. The Productos list prices are NOT here: they are the last resort of the
    price, needed by few units, and carrying ten more columns through every row of a big set costs more than the
    rest of the row (`_fallback_rows` reads them for the units that need them)."""
    return [product.costo, product.moneda_costo, product.iva, product.envio, product.subcategoria_id]


def _rows(db: Session, query: Any) -> list[Any]:
    """Run a column query through the connection of the session's transaction. `Session.execute` wraps the rows
    of a statement built from ORM entities in the ORM loading layer, which costs about 3x the whole fetch on a
    25k-row set; these statements select plain columns and need none of it."""
    return db.connection().execute(query).all()


def _item_rows(db: Session, item_ids: Optional[Sequence[str]], f: Optional[PublicationFilter]) -> list[Any]:
    """One row per publication: its price inputs and its ITEM-LEVEL unit (link, product cost fields). A filter is
    the list's own base select (one pass over the set, no second join to `ml_items`); explicit ids are the same
    joins over `ml_items` keyed by the id array. The item-level link is not filtered by `match_status`, like the
    list's: the table's CHECK constraint makes `producto_item_id` non-null exactly when the status is `linked`."""
    if f is not None:
        columns = [
            T.i.item_id,
            T.i.listing_type_id,
            _tags(T.i),
            T.i.price.label("item_price"),
            T.sp.amount.label("sale_price"),
            _campaign(T.i).label("campaign"),
            T.l.producto_item_id,
            *_product_columns(T.p),
        ]
        return _rows(db, build_base_select(f, *columns))
    item, sale, link, product = (
        aliased(MlItem, name="mi"),
        aliased(MlItemSalePrice, name="msp"),
        aliased(MlItemProductLink, name="ml"),
        aliased(ProductoERP, name="mp"),
    )
    joins = orm_join(
        orm_join(
            orm_join(
                item,
                sale,
                and_(sale.item_id == item.item_id, sale.gone_at.is_(None), sale.http_status.between(200, 299)),
                isouter=True,
            ),
            link,
            and_(link.item_id == item.item_id, link.variation_id == LINK_ITEM_LEVEL),
            isouter=True,
        ),
        product,
        product.item_id == link.producto_item_id,
        isouter=True,
    )
    query = (
        select(
            item.item_id,
            item.listing_type_id,
            _tags(item),
            item.price.label("item_price"),
            sale.amount.label("sale_price"),
            _campaign(item).label("campaign"),
            link.producto_item_id,
            *_product_columns(product),
        )
        .select_from(joins)
        .where(item.item_id.in_(_ids_param(item_ids or ())))
    )
    return _rows(db, query)


def _variation_rows(db: Session, ids: Sequence[str]) -> list[Any]:
    v = MlItemVariation
    return _rows(
        db,
        select(v.item_id, v.variation_id)
        .where(v.item_id.in_(_ids_param(ids)), v.gone_at.is_(None))
        .order_by(v.item_id, v.variation_id),
    )


def _variation_link_rows(db: Session, ids: Sequence[str]) -> list[Any]:
    """The variation-level links (and their products) of the given publications, item level excluded."""
    link, product = MlItemProductLink, ProductoERP
    return _rows(
        db,
        select(link.item_id, link.variation_id, link.producto_item_id, *_product_columns(product))
        .select_from(orm_join(link, product, product.item_id == link.producto_item_id))
        .where(
            link.item_id.in_(_ids_param(ids)), link.variation_id != LINK_ITEM_LEVEL, link.match_status == LINK_LINKED
        ),
    )


def _fallback_rows(db: Session, product_ids: Sequence[int]) -> list[Any]:
    """The Productos list prices of the given products (a product with none has no row)."""
    pricing = ProductoPricing
    return _rows(
        db,
        select(pricing.item_id, *(getattr(pricing, column) for column in FALLBACK_COLUMNS)).where(
            pricing.item_id.in_(select(cast(_unnested(product_ids), Integer)))
        ),
    )


def currency_of(value: Any) -> Optional[str]:
    return getattr(value, "value", value)


def _has_price(value: Any) -> bool:
    return value is not None and value > 0


def fetch_inputs(
    db: Session, *, item_ids: Optional[Sequence[str]] = None, f: Optional[PublicationFilter] = None
) -> dict[str, PublicationInputs]:
    """Inputs of the given publications, or of every publication of a (PM-resolved) filter; ids that do not
    exist are absent. Exactly one of `item_ids` / `f`. Three statements, four when some unit has no price of its own,
    whatever the size of the set."""
    if (item_ids is None) == (f is None):
        raise ValueError("pass exactly one of `item_ids` or `f`")
    if item_ids is not None and not item_ids:
        return {}
    items = _item_rows(db, item_ids, f)
    if not items:
        return {}
    variations: dict[str, list[int]] = {}
    for item_id, variation_id in _variation_rows(db, [row[0] for row in items]):
        variations.setdefault(item_id, []).append(variation_id)
    # Always the third statement (an empty array when no publication has variations): a fixed count.
    links: dict[tuple[str, int], Any] = {(row[0], row[1]): row for row in _variation_link_rows(db, list(variations))}

    # The list prices are read, in one more statement, for the products of the units whose publication has no
    # price of its own (`_pick_price` reads them only then); none needs them, no statement.
    priceless = {row[0] for row in items if not (_has_price(row[4]) or _has_price(row[3]))}
    needing: set[int] = set()
    if priceless:
        needing.update(row[6] for row in items if row[0] in priceless and row[6] is not None)
        needing.update(row[2] for (item_id, _variation), row in links.items() if item_id in priceless)
    fallbacks: dict[int, dict[str, Optional[float]]] = {pid: dict.fromkeys(FALLBACK_COLUMNS) for pid in needing}
    for pid, *prices in _fallback_rows(db, sorted(needing)) if needing else ():
        fallbacks[pid] = {column: _floats(price) for column, price in zip(FALLBACK_COLUMNS, prices)}

    # A product's fields converted once, however many publications link it: `(costo, moneda, iva, envio, subcat)`.
    products: dict[int, tuple[Any, ...]] = {}

    def product_of(pid: int, costo: Any, moneda: Any, iva: Any, envio: Any, subcategoria_id: Any) -> tuple[Any, ...]:
        found = products[pid] = (
            None if costo is None else float(costo),
            getattr(moneda, "value", moneda),
            DEFAULT_IVA if iva is None else float(iva),
            None if envio is None else float(envio),
            subcategoria_id,
        )
        return found

    def variation_unit(
        item: UnitInputs, pid: int, costo: Any, moneda: Any, iva: Any, envio: Any, subcat: Any
    ) -> UnitInputs:
        """The unit of a variation with a link of its own: the publication's inputs and ITS product."""
        found = products.get(pid) or product_of(pid, costo, moneda, iva, envio, subcat)
        return UnitInputs(
            item.item_id,
            item.listing_type_id,
            item.tags,
            item.sale_terms_campaign,
            item.sale_price,
            item.item_price,
            fallbacks.get(pid, _NO_PRICES),
            pid,
            *found,
        )

    inputs: dict[str, PublicationInputs] = {}
    for (
        item_id,
        listing_type_id,
        tags,
        item_price,
        sale_price,
        campaign,
        pid,
        costo,
        moneda,
        iva,
        envio,
        subcat,
    ) in items:
        tags = tuple(tags) if tags else ()
        sale = None if sale_price is None else float(sale_price)
        price = None if item_price is None else float(item_price)
        if pid is None:
            item_unit = UnitInputs(item_id, listing_type_id, tags, campaign, sale, price)
        else:
            found = products.get(pid) or product_of(pid, costo, moneda, iva, envio, subcat)
            item_unit = UnitInputs(
                item_id, listing_type_id, tags, campaign, sale, price, fallbacks.get(pid, _NO_PRICES), pid, *found
            )
        variation_ids = variations.get(item_id)
        if variation_ids is None:
            inputs[item_id] = PublicationInputs(item_id, item_unit, (), ())
            continue
        own: list[Optional[UnitInputs]] = []
        for variation_id in variation_ids:
            link = links.get((item_id, variation_id))
            own.append(None if link is None else variation_unit(item_unit, *link[2:]))
        inputs[item_id] = PublicationInputs(item_id, item_unit, tuple(own), tuple(variation_ids))
    return inputs
