"""The variation sub-rows of one publication (design §3.3, addendum decision 5).

A publication whose variations carry different SKU/EAN is several products, so the expanded row shows, per live
variation: its own data (SKU, quantities, attributes), the product it is priced with and, for users who may see
margins, that product's cost and the variation's markup.

* The product of a sub-row is the variation's OWN link when it is `linked` to a product that still exists, else the
  item-level link (variation 0). It is the very rule `markup_inputs.fetch_inputs` prices with, so the product shown
  and the markup shown always agree; `inherited` says which of the two it is.
* Cost and markup are not computed here. The markup is `markup_service.compute_markups` (the list's own entry
  point, so a sub-row equals the unit the list aggregates) and the Ads cost is the one that service applies: per
  publication, spread per unit, identical on every variation.
* Two statements for the data, whatever the number of variations: one for the item with its variations, links and
  products (this is why the module names the product catalog, see `test_static_guards.py`), one for the markup
  path's inputs. Nothing here writes.
"""

from __future__ import annotations

from dataclasses import dataclass
from typing import Any, Mapping, Optional

from sqlalchemy import and_, func, select
from sqlalchemy.orm import Session, aliased, join as orm_join

from app.models.ml_publications import MlItem, MlItemProductLink, MlItemVariation
from app.models.producto import ProductoERP
from app.services.ml_publications.view import markup_service
from app.services.ml_publications.view.filters import LINK_CONFLICT, LINK_ITEM_LEVEL, LINK_LINKED, LINK_SOURCE_MANUAL
from app.services.ml_publications.view.markup import UnitMarkup
from app.services.ml_publications.view.markup_inputs import currency_of
from app.services.ml_publications.view.markup_service import ItemMarkup, MarkupQuery

STALE_REASON = "desactualizado"  # the variation is not among those the markup priced: it changed in between


@dataclass(frozen=True)
class VariationsResult:
    """The sub-rows, the publication's Ads figures (when Ads was applied) and whether the Ads provider failed."""

    variations: list[dict[str, Any]]
    ads: Optional[dict[str, Any]] = None
    ads_failed: bool = False


def link_state_of(match_status: Optional[str], source: Optional[str]) -> str:
    """The list's `link.state` rule, over the columns of one link row (`None` = no row)."""
    if match_status is None:
        return "no_evaluado"
    if match_status == LINK_CONFLICT:
        return "conflicto"
    if match_status == LINK_LINKED:
        return "manual" if source == LINK_SOURCE_MANUAL else "auto"
    return "sin_producto"


def _rows(db: Session, item_id: str) -> list[Any]:
    """One row per live variation (ordered by id) with its own linked product and the item-level one; a single row
    with a null `variation_id` when the publication has no variations; no row when it does not exist."""
    item, var = aliased(MlItem, name="vi"), aliased(MlItemVariation, name="vv")
    own, own_product = aliased(MlItemProductLink, name="vl"), aliased(ProductoERP, name="vp")
    base, base_product = aliased(MlItemProductLink, name="bl"), aliased(ProductoERP, name="bp")
    joins = orm_join(
        orm_join(
            orm_join(
                orm_join(
                    orm_join(item, var, and_(var.item_id == item.item_id, var.gone_at.is_(None)), isouter=True),
                    own,
                    and_(
                        own.item_id == var.item_id,
                        own.variation_id == var.variation_id,
                        own.match_status == LINK_LINKED,
                    ),
                    isouter=True,
                ),
                own_product,
                own_product.item_id == own.producto_item_id,
                isouter=True,
            ),
            base,
            and_(base.item_id == item.item_id, base.variation_id == LINK_ITEM_LEVEL),
            isouter=True,
        ),
        base_product,
        base_product.item_id == base.producto_item_id,
        isouter=True,
    )
    query = (
        select(
            var.variation_id,
            func.coalesce(var.seller_sku, var.seller_custom_field).label("seller_sku"),
            var.user_product_id,
            var.available_quantity,
            var.sold_quantity,
            var.raw["attribute_combinations"].label("attributes"),
            own.source.label("own_source"),
            own_product.item_id.label("own_product_id"),
            own_product.codigo.label("own_codigo"),
            own_product.descripcion.label("own_descripcion"),
            own_product.marca.label("own_marca"),
            own_product.costo.label("own_costo"),
            own_product.moneda_costo.label("own_moneda"),
            base.match_status.label("base_status"),
            base.source.label("base_source"),
            base_product.item_id.label("base_product_id"),
            base_product.codigo.label("base_codigo"),
            base_product.descripcion.label("base_descripcion"),
            base_product.marca.label("base_marca"),
            base_product.costo.label("base_costo"),
            base_product.moneda_costo.label("base_moneda"),
        )
        .select_from(joins)
        .where(item.item_id == item_id)
        .order_by(var.variation_id)
    )
    return list(db.connection().execute(query).all())


def _attributes(raw: Any) -> list[dict[str, Any]]:
    """`attribute_combinations` of the variation as `{name, value}` pairs (what tells one variation from another)."""
    return [
        {"name": a.get("name") or a.get("id"), "value": a.get("value_name")}
        for a in (raw if isinstance(raw, list) else [])
        if isinstance(a, dict)
    ]


def _round(value: Optional[float]) -> Optional[float]:
    return None if value is None else round(value, 2)


def _sub_row(row: Any, margin: bool) -> dict[str, Any]:
    use_own = row.own_product_id is not None
    prefix = "own" if use_own else "base"
    product_id = row.own_product_id if use_own else row.base_product_id
    state = link_state_of(LINK_LINKED, row.own_source) if use_own else link_state_of(row.base_status, row.base_source)
    out: dict[str, Any] = {
        "variation_id": row.variation_id,
        "seller_sku": row.seller_sku,
        "user_product_id": row.user_product_id,
        "available_quantity": row.available_quantity,
        "sold_quantity": row.sold_quantity,
        "attributes": _attributes(row.attributes),
        "link": {
            "state": state,
            "inherited": not use_own,
            "producto_item_id": product_id,
            "codigo": getattr(row, f"{prefix}_codigo"),
            "descripcion": getattr(row, f"{prefix}_descripcion"),
            "marca": getattr(row, f"{prefix}_marca"),
        },
    }
    if margin:
        costo = getattr(row, f"{prefix}_costo")
        out["costo"] = (
            None if product_id is None else {"amount": costo, "currency": currency_of(getattr(row, f"{prefix}_moneda"))}
        )
    return out


def _markup_out(unit: UnitMarkup) -> dict[str, Any]:
    return {"value": _round(unit.value), "reason": unit.reason}


def _publication_ads(item: ItemMarkup) -> Optional[dict[str, Any]]:
    if item.ads is None:
        return None
    return {
        "state": item.ads.state,
        "amount": _round(item.ads.amount),
        "units": item.ads.units,
        "per_unit": _round(item.ads.per_unit),
    }


def list_variations(db: Session, item_id: str, markup: Optional[MarkupQuery] = None) -> Optional[VariationsResult]:
    """The sub-rows of `item_id`, or `None` when the publication is not in the store. `markup` (its presence means
    the caller may see margins) adds cost and markup to each sub-row, after Ads when the query carries a plan.
    A publication with no live variations has no sub-rows to price: the Ads status still says what was asked, but
    there are no `publication` figures, and nothing is computed."""
    rows = _rows(db, item_id)
    if not rows:
        return None
    live = [row for row in rows if row.variation_id is not None]
    sub_rows = [_sub_row(row, markup is not None) for row in live]
    if markup is None or not live:
        return VariationsResult(sub_rows)
    computed = markup_service.compute_markups(db, markup.pricing_db, item_ids=[item_id], ads=markup.ads)
    item = computed.items.get(item_id)
    # Matched by variation id, never by position: a variation may have been replaced between the two reads.
    units: Mapping[int, UnitMarkup] = {}
    if item is not None and len(item.variation_ids) == len(item.markup.variations):
        units = dict(zip(item.variation_ids, item.markup.variations))
    for sub_row in sub_rows:
        unit = units.get(sub_row["variation_id"])
        sub_row["markup"] = _markup_out(unit) if unit is not None else {"value": None, "reason": STALE_REASON}
    return VariationsResult(sub_rows, _publication_ads(item) if item is not None else None, computed.ads_failed)
