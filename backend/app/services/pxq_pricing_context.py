"""Resolves per-publication pricing context (cost, IVA, commission base) for
a PxQ tier's MLA (slice A1 of `pxq-markup-antes-de-publicar`).

Mirrors `ml_promotions_pricing._resolve_pricing_context`'s discipline: every
irresolvable input -- unlinked MLA, zero/missing product cost, unconvertible
currency, missing IVA, no resolvable commission base -- collapses to a
single `None`, never a partial context and never a raised exception.
`markup_for_tiers` (`pxq_markup_service.py`) reads this as
"product_data_missing" when `None`.

`producto.moneda_costo`/`producto.iva` carry `default=` at the ORM level
only (`ProductoERP`, `app/models/producto.py`) -- rows written by the ERP
sync bypass that default entirely, so `moneda_costo IS NULL` and
`iva IS NULL` are both reachable in production data. Handing a USD cost to
`convertir_a_pesos` (`pricing_calculator.py`) without a resolved
`tipo_cambio`, or an unrecognized/`None` currency, falls through to
`return costo` UNCONVERTED -- silently fabricating a plausible-looking but
wrong ARS figure instead of reporting an unresolved context. `producto.iva`
being `None` would instead pass validation here and raise a `TypeError`
later inside `calcular_markup_pxq`. Both collapse to `None` here, before
either can happen.

Deliberately does NOT call `resolver_costo_envio`: that resolves the
PER-UNIT `producto.envio` field, and feeding a per-unit shipping figure to a
PxQ tier (an N-unit order) is exactly the unit-vs-order confusion
`ShipmentShippingCost` (`pxq_markup.py`) exists to make structurally
impossible. Shipping for a PxQ tier comes ONLY from
`resolve_tier_shipping(tier)` on `costo_envio_total`.
"""

from __future__ import annotations

from dataclasses import dataclass
from typing import Optional

from sqlalchemy.orm import Session

from app.core.logging import get_logger
from app.models.producto import ProductoERP
from app.models.publicacion_ml import PublicacionML
from app.services.pricing_calculator import (
    convertir_a_pesos,
    obtener_comision_base,
    obtener_grupo_subcategoria,
    obtener_tipo_cambio_actual,
)

logger = get_logger(__name__)


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


def resolve_pxq_pricing_context(db: Session, mla: str) -> Optional[PxqPricingContext]:
    """Resolves cost/IVA/commission context for `mla`.

    Join chain: `MlPxqTier.item_id` (MLA) -> `PublicacionML.mla` ->
    `PublicacionML.item_id` (ERP) -> `ProductoERP`.

    Returns `None` (never raises) when the publication is unlinked, the
    product cost is zero/missing, or no commission base resolves -- the
    exact one-broad-try/except discipline as `_resolve_pricing_context`
    (`ml_promotions_pricing.py`).
    """
    try:
        publicacion = db.query(PublicacionML).filter(PublicacionML.mla == mla).first()
        if not publicacion:
            return None

        producto = db.query(ProductoERP).filter(ProductoERP.item_id == publicacion.item_id).first()
        if not producto or not producto.costo:
            return None

        if producto.iva is None:
            return None

        tipo_cambio = None
        if producto.moneda_costo == "USD":
            tipo_cambio = obtener_tipo_cambio_actual(db, "USD")
            if tipo_cambio is None:
                return None
        elif producto.moneda_costo != "ARS":
            # Unrecognized/`None` currency (e.g. an ERP-synced row with
            # `moneda_costo IS NULL`) -- `convertir_a_pesos` only special-
            # cases the literal string "ARS", so anything else must NOT
            # fall through to its unconverted-passthrough branch.
            return None

        costo_ars = convertir_a_pesos(producto.costo, producto.moneda_costo, tipo_cambio)
        grupo_id = obtener_grupo_subcategoria(db, producto.subcategoria_id)
        comision_base = obtener_comision_base(db, publicacion.pricelist_id, grupo_id)
    except Exception as e:
        logger.warning("Error resolving PxQ pricing context for mla %s: %s", mla, e)
        return None

    if comision_base is None:
        return None

    return PxqPricingContext(
        costo_ars=costo_ars,
        comision_base_pct=comision_base,
        iva=producto.iva,
        grupo_id=grupo_id,
    )
