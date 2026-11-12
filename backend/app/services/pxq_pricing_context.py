"""Resolves per-publication pricing context (cost, IVA, commission base) for
a PxQ tier's MLA (slice A1 of `pxq-markup-antes-de-publicar`).

The context is priced on the publication header's own inputs (S11b,
2026-11-12): the product is the one the publication's item-level link
(`ml_item_product_links`) points to, and the commission list is the one ML
charges the item (`resolve_pricelist` on the `ml_items` listing type,
campaign tag and installments sale term). Neither `publicaciones_ml.item_id`
nor its stored `pricelist_id` is read.

Every irresolvable input collapses to a `PxqPricingUnavailable` carrying the
header's reason for it (`view/markup.py`, `pricelist_resolver.py`), never a
partial context and never a raised exception:

* `sin_item_ml`: the MLA is not in the store (`ml_items`).
* `sin_vinculo`: the publication has no item-level product link.
* `sin_costo`: the linked product has no cost (or no longer exists).
* `cofinanciada` / `sin_lista`: there is no list of ours for the item.
* `sin_comision`: no commission for that list and group.
* `product_data_missing`: what only PxQ refuses to guess (below), or an
  unexpected read error.

`producto.moneda_costo`/`producto.iva` carry `default=` at the ORM level
only (`ProductoERP`, `app/models/producto.py`) -- rows written by the ERP
sync bypass that default entirely, so `moneda_costo IS NULL` and
`iva IS NULL` are both reachable in production data. Handing a USD cost to
`convertir_a_pesos` (`pricing_calculator.py`) without a resolved
`tipo_cambio`, or an unrecognized/`None` currency, falls through to
`return costo` UNCONVERTED -- silently fabricating a plausible-looking but
wrong ARS figure instead of reporting an unresolved context. `producto.iva`
being `None` would instead pass validation here and raise a `TypeError`
later inside `calcular_markup_pxq`. Both are `product_data_missing` here,
before either can happen.

Deliberately does NOT call `resolver_costo_envio`: that resolves the
PER-UNIT `producto.envio` field, and feeding a per-unit shipping figure to a
PxQ tier (an N-unit order) is exactly the unit-vs-order confusion
`ShipmentShippingCost` (`pxq_markup.py`) exists to make structurally
impossible. Shipping for a PxQ tier comes ONLY from
`resolve_tier_shipping(tier)` on `costo_envio_total`.
"""

from __future__ import annotations

from dataclasses import dataclass
from typing import Union

from sqlalchemy.orm import Session

from app.core.logging import get_logger
from app.models.ml_publications import MlItem, MlItemProductLink
from app.models.producto import ProductoERP
from app.services.ml_publications.pricelist_resolver import resolve_pricelist
from app.services.ml_publications.view.filters import LINK_ITEM_LEVEL
from app.services.ml_publications.view.markup import REASON_SIN_COMISION, REASON_SIN_COSTO, REASON_SIN_VINCULO
from app.services.pricing_calculator import (
    convertir_a_pesos,
    obtener_comision_base,
    obtener_grupo_subcategoria,
    obtener_tipo_cambio_actual,
)

logger = get_logger(__name__)

REASON_SIN_ITEM_ML = "sin_item_ml"
REASON_PRODUCT_DATA_MISSING = "product_data_missing"


@dataclass(frozen=True)
class PxqPricingContext:
    """Resolved cost/commission context shared by every tier of one
    publication. Resolved ONCE per `markup_for_tiers` call (not per-tier),
    so all tiers of one MLA follow the identical code path -- no
    publication-specific branching."""

    costo_ars: float
    comision_base_pct: float
    iva: float
    grupo_id: int


@dataclass(frozen=True)
class PxqPricingUnavailable:
    """Why the context of a publication could not be resolved: one reason, shared by all its tiers."""

    reason: str


def resolve_pxq_pricing_context(db: Session, mla: str) -> Union[PxqPricingContext, PxqPricingUnavailable]:
    """Resolves cost/IVA/commission context for `mla` from the header's inputs.

    Join chain: `MlPxqTier.item_id` (MLA) -> `ml_items` (listing type, tags,
    installments campaign) and `ml_item_product_links` (item level) ->
    `ProductoERP`.

    Returns `PxqPricingUnavailable` (never raises) when any input does not
    resolve, with the reason the header gives for it (module docstring).
    """
    try:
        item = (
            db.query(MlItem.listing_type_id, MlItem.tags, MlItem.installments_campaign)
            .filter(MlItem.item_id == mla)
            .one_or_none()
        )
        if item is None:
            return PxqPricingUnavailable(REASON_SIN_ITEM_ML)

        producto_item_id = (
            db.query(MlItemProductLink.producto_item_id)
            .filter(MlItemProductLink.item_id == mla, MlItemProductLink.variation_id == LINK_ITEM_LEVEL)
            .scalar()
        )
        if producto_item_id is None:
            return PxqPricingUnavailable(REASON_SIN_VINCULO)

        producto = db.query(ProductoERP).filter(ProductoERP.item_id == producto_item_id).one_or_none()
        if not producto or not producto.costo:
            return PxqPricingUnavailable(REASON_SIN_COSTO)

        resolution = resolve_pricelist(item.listing_type_id, item.tags or (), item.installments_campaign)
        if resolution.pricelist_id is None:
            return PxqPricingUnavailable(resolution.reason)

        if producto.iva is None:
            return PxqPricingUnavailable(REASON_PRODUCT_DATA_MISSING)

        tipo_cambio = None
        if producto.moneda_costo == "USD":
            tipo_cambio = obtener_tipo_cambio_actual(db, "USD")
            if tipo_cambio is None:
                return PxqPricingUnavailable(REASON_PRODUCT_DATA_MISSING)
        elif producto.moneda_costo != "ARS":
            # Unrecognized/`None` currency (e.g. an ERP-synced row with
            # `moneda_costo IS NULL`) -- `convertir_a_pesos` only special-
            # cases the literal string "ARS", so anything else must NOT
            # fall through to its unconverted-passthrough branch.
            return PxqPricingUnavailable(REASON_PRODUCT_DATA_MISSING)

        costo_ars = convertir_a_pesos(producto.costo, producto.moneda_costo, tipo_cambio)
        grupo_id = obtener_grupo_subcategoria(db, producto.subcategoria_id)
        comision_base = obtener_comision_base(db, resolution.pricelist_id, grupo_id)
    except Exception as e:
        logger.warning("Error resolving PxQ pricing context for mla %s: %s", mla, e)
        return PxqPricingUnavailable(REASON_PRODUCT_DATA_MISSING)

    if not comision_base:
        return PxqPricingUnavailable(REASON_SIN_COMISION)

    return PxqPricingContext(
        costo_ars=costo_ars,
        comision_base_pct=comision_base,
        iva=producto.iva,
        grupo_id=grupo_id,
    )
