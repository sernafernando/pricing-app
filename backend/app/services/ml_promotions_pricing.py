"""
Per-promo "nuestro markup" enrichment for the ML Seller Promotions panel.

READ-ONLY. Given a list of promo dicts (as returned by
`fetch_item_promotions`), enriches each with `nuestro_markup`: the seller's
markup percentage computed on the promo's effective revenue (effective
discounted price + ML co-funding, when applicable).

Cost/commission context (item, pricelist, cost, IVA, envío, tipo de cambio)
is resolved ONCE per request from `PublicacionML` + `ProductoERP`; each promo
then only runs cheap arithmetic on its own effective revenue. Mirrors the
exact price->markup chain used by `/precios/calcular-markup` and
`calcular_markup_oferta` (pricing.py).

Never crashes: any promo whose cost/publication/effective-price cannot be
resolved gets `nuestro_markup = None`.
"""

from typing import Any, Dict, List, Optional

from sqlalchemy.orm import Session

from app.core.logging import get_logger
from app.models.producto import ProductoERP
from app.models.publicacion_ml import PublicacionML
from app.services.envio_real_service import resolver_costo_envio
from app.services.pricing_calculator import (
    calcular_comision_ml_total,
    calcular_limpio,
    calcular_markup,
    convertir_a_pesos,
    obtener_comision_base,
    obtener_grupo_subcategoria,
    obtener_tipo_cambio_actual,
)

logger = get_logger(__name__)


def _co_funding_amount(promo: Dict[str, Any]) -> float:
    """ML's co-funded portion of the discount, in currency units.

    SMART: `(meli_percentage / 100) * original_price`, read from
    `promo["payload"]["meli_percentage"]`. Any other promo type
    (SELLER_CAMPAIGN, DEAL, PRICE_DISCOUNT, unknown) funds nothing: 0.0.
    Defensive against missing/None inputs — always returns 0.0 on any
    unresolvable input rather than raising.
    """
    if promo.get("promotion_type") != "SMART":
        return 0.0

    payload = promo.get("payload") or {}
    meli_percentage = payload.get("meli_percentage")
    original_price = promo.get("original_price")

    if meli_percentage is None or original_price is None:
        return 0.0

    try:
        return (float(meli_percentage) / 100) * float(original_price)
    except (TypeError, ValueError):
        return 0.0


def _effective_discounted_price(promo: Dict[str, Any]) -> Optional[float]:
    """`price` when the promo is started (price > 0); otherwise
    `suggested_discounted_price` (candidate). None when neither is usable."""
    price = promo.get("price")
    if price and price > 0:
        return float(price)

    suggested = promo.get("suggested_discounted_price")
    if suggested and suggested > 0:
        return float(suggested)

    return None


def enriquecer_markup_por_promo(db: Session, mla: str, promociones: List[Dict[str, Any]]) -> List[Dict[str, Any]]:
    """Adds `nuestro_markup` (Optional[float], percentage) to each promo dict
    in `promociones`, mutating them in place and returning the same list.

    Resolves item/pricelist/cost/commission context ONCE per request from
    `mla`. If the publication or the product cost cannot be resolved, every
    promo in the list gets `nuestro_markup = None` (no exception).
    """
    if not promociones:
        return promociones

    try:
        publicacion = db.query(PublicacionML).filter(PublicacionML.mla == mla).first()
        if not publicacion:
            for promo in promociones:
                promo["nuestro_markup"] = None
            return promociones

        producto = db.query(ProductoERP).filter(ProductoERP.item_id == publicacion.item_id).first()
        if not producto or not producto.costo:
            for promo in promociones:
                promo["nuestro_markup"] = None
            return promociones

        tipo_cambio = None
        if producto.moneda_costo == "USD":
            tipo_cambio = obtener_tipo_cambio_actual(db, "USD")

        costo_ars = convertir_a_pesos(producto.costo, producto.moneda_costo, tipo_cambio)
        grupo_id = obtener_grupo_subcategoria(db, producto.subcategoria_id)
        comision_base = obtener_comision_base(db, publicacion.pricelist_id, grupo_id)
        costo_envio = resolver_costo_envio(db, producto)
    except Exception as e:
        logger.warning("Error resolving pricing context for mla %s: %s", mla, e)
        for promo in promociones:
            promo["nuestro_markup"] = None
        return promociones

    if comision_base is None:
        for promo in promociones:
            promo["nuestro_markup"] = None
        return promociones

    for promo in promociones:
        promo["nuestro_markup"] = _calcular_nuestro_markup(
            db=db,
            promo=promo,
            costo_ars=costo_ars,
            comision_base=comision_base,
            iva=producto.iva,
            costo_envio=costo_envio,
            grupo_id=grupo_id,
        )

    return promociones


def _calcular_nuestro_markup(
    db: Session,
    promo: Dict[str, Any],
    costo_ars: float,
    comision_base: float,
    iva: float,
    costo_envio: float,
    grupo_id: int,
) -> Optional[float]:
    effective_price = _effective_discounted_price(promo)
    if effective_price is None:
        return None

    try:
        co_funding = _co_funding_amount(promo)
        effective_revenue = effective_price + co_funding

        comisiones = calcular_comision_ml_total(effective_revenue, comision_base, iva, db=db)
        limpio = calcular_limpio(
            effective_revenue, iva, costo_envio, comisiones["comision_total"], db=db, grupo_id=grupo_id
        )
        return calcular_markup(limpio, costo_ars) * 100
    except Exception as e:
        logger.warning(
            "Error calculando nuestro_markup para promo %s de mla %s: %s",
            promo.get("promotion_id"),
            promo.get("mla"),
            e,
        )
        return None
