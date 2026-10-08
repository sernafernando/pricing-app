"""The markup INPUTS of a set of publications (design §4.3, §4.4): extracted in three statements, whatever the size.

SQL only extracts; the maths is `markup.unit_markup` (P2). For each publication the three statements read:

1. the item: listing type, tags, the price inputs (current sale price and `ml_items.price`) and the installments
   campaign sale term, which is read ONLY when no campaign tag is present (the tag wins, see `pricelist_resolver`);
2. its live variations;
3. every `linked` unit (item level and per variation) with the linked product's cost fields and the Productos
   list prices the fallback reads.

The set is either explicit ids (a page) or a `PublicationFilter` (the whole filtered set, for sorting and
filtering by markup). Statements 2 and 3 are scoped by the ids statement 1 returned, bound as ONE array
parameter, so the filter's joins run once and the statement text does not grow with the set.

This module is the second view module allowed to name the product catalog (see `test_static_guards.py`): it reads
the cost fields of the products a publication is linked to, in one join from the stored links, and never writes.
"""

from __future__ import annotations

from dataclasses import dataclass
from typing import Any, Optional, Sequence

from sqlalchemy import ARRAY, Text, and_, any_, case, cast, func, literal, literal_column, select
from sqlalchemy.dialects.postgresql import JSONPATH
from sqlalchemy.orm import Session, aliased, join as orm_join

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


@dataclass(frozen=True)
class PublicationInputs:
    """Everything needed to price one publication: its item-level unit and one entry per live variation
    (`None` when that variation has no link of its own; the fallback to the item-level unit is `markup`'s)."""

    item_id: str
    item_unit: UnitInputs
    variation_units: tuple[Optional[UnitInputs], ...]


def _ids_param(ids: Sequence[str]) -> Any:
    return any_(literal(list(ids), ARRAY(Text)))


def _campaign(mi: Any) -> Any:
    """The sale-term campaign, evaluated only when no campaign tag is present."""
    term = func.jsonb_path_query_first(mi.raw, cast(literal(CAMPAIGN_SALE_TERM), JSONPATH)).op("#>>")(
        literal_column("'{}'")
    )
    return case((func.coalesce(mi.tags, literal([], ARRAY(Text))).overlap(list(CAMPAIGN_TAGS)), None), else_=term)


def _floats(value: Any) -> Optional[float]:
    return None if value is None else float(value)


def _item_rows(db: Session, item_ids: Optional[Sequence[str]], f: Optional[PublicationFilter]) -> list[Any]:
    mi, sp = aliased(MlItem, name="mi"), aliased(MlItemSalePrice, name="msp")
    query = select(
        mi.item_id,
        mi.listing_type_id,
        mi.tags,
        mi.price.label("item_price"),
        sp.amount.label("sale_price"),
        _campaign(mi).label("campaign"),
    ).select_from(
        orm_join(
            mi,
            sp,
            and_(sp.item_id == mi.item_id, sp.gone_at.is_(None), sp.http_status.between(200, 299)),
            isouter=True,
        )
    )
    if item_ids is not None:
        query = query.where(mi.item_id == _ids_param(item_ids))
    else:
        query = query.where(mi.item_id.in_(build_base_select(f, T.i.item_id)))
    return db.execute(query).all()


def _variation_rows(db: Session, ids: Sequence[str]) -> list[Any]:
    v = MlItemVariation
    return db.execute(
        select(v.item_id, v.variation_id)
        .where(v.item_id == _ids_param(ids), v.gone_at.is_(None))
        .order_by(v.item_id, v.variation_id)
    ).all()


def _link_rows(db: Session, ids: Sequence[str]) -> list[Any]:
    link, product, pricing = MlItemProductLink, ProductoERP, ProductoPricing
    prices = [getattr(pricing, column) for column in FALLBACK_COLUMNS]
    return db.execute(
        select(
            link.item_id,
            link.variation_id,
            link.producto_item_id,
            product.costo,
            product.moneda_costo,
            product.iva,
            product.envio,
            product.subcategoria_id,
            *prices,
        )
        .select_from(
            orm_join(
                orm_join(link, product, product.item_id == link.producto_item_id),
                pricing,
                pricing.item_id == product.item_id,
                isouter=True,
            )
        )
        .where(link.item_id == _ids_param(ids), link.match_status == LINK_LINKED)
    ).all()


def _currency(value: Any) -> Optional[str]:
    return getattr(value, "value", value)


def fetch_inputs(
    db: Session, *, item_ids: Optional[Sequence[str]] = None, f: Optional[PublicationFilter] = None
) -> dict[str, PublicationInputs]:
    """Inputs of the given publications, or of every publication of a (PM-resolved) filter; ids that do not
    exist are absent. Exactly one of `item_ids` / `f`."""
    if (item_ids is None) == (f is None):
        raise ValueError("pass exactly one of `item_ids` or `f`")
    if item_ids is not None and not item_ids:
        return {}
    items = _item_rows(db, item_ids, f)
    if not items:
        return {}
    ids = [row.item_id for row in items]
    variations: dict[str, list[int]] = {}
    for item_id, variation_id in _variation_rows(db, ids):
        variations.setdefault(item_id, []).append(variation_id)
    links: dict[tuple[str, int], Any] = {(row.item_id, row.variation_id): row for row in _link_rows(db, ids)}

    def unit(item: Any, link: Any) -> UnitInputs:
        common: dict[str, Any] = dict(
            item_id=item.item_id,
            listing_type_id=item.listing_type_id,
            tags=tuple(item.tags or ()),
            sale_terms_campaign=item.campaign,
            sale_price=_floats(item.sale_price),
            item_price=_floats(item.item_price),
        )
        if link is None:
            return UnitInputs(**common)
        return UnitInputs(
            **common,
            fallback_prices={column: _floats(getattr(link, column)) for column in FALLBACK_COLUMNS},
            producto_item_id=link.producto_item_id,
            costo=_floats(link.costo),
            moneda_costo=_currency(link.moneda_costo),
            iva=DEFAULT_IVA if link.iva is None else float(link.iva),
            envio=_floats(link.envio),
            subcategoria_id=link.subcategoria_id,
        )

    inputs: dict[str, PublicationInputs] = {}
    for item in items:
        own = [
            unit(item, links[(item.item_id, v)]) if (item.item_id, v) in links else None
            for v in variations.get(item.item_id, ())
        ]
        inputs[item.item_id] = PublicationInputs(
            item.item_id, unit(item, links.get((item.item_id, LINK_ITEM_LEVEL))), tuple(own)
        )
    return inputs
