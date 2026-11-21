"""
Service para recalcular markups de todos los productos con precio.

Extraído del endpoint /recalcular-markups para poder ejecutarse
tanto desde la API como desde scripts standalone.
"""

import logging
from typing import Dict, Iterable, List, Optional, Tuple

from sqlalchemy.orm import Session

from app.models.producto import ProductoERP, ProductoPricing
from app.services.envio_real_service import resolver_costos_envio_batch
from app.services.pricing_calculator import (
    VARIOS_DEFAULT,
    calcular_comision_ml_total,
    calcular_limpio,
    calcular_markup,
    calcular_markup_oferta,
    calcular_markup_rebate,
    costos_ars_actuales,
    limpio_web_transferencia,
    obtener_comision_base,
    obtener_constantes_pricing,
    obtener_grupo_subcategoria,
    obtener_tipo_cambio_actual,
)

logger = logging.getLogger(__name__)


def recalcular_markups(db: Session) -> Dict:
    """
    Recalcula markups de todos los productos que tienen precio_lista_ml.

    Returns:
        Dict con status, actualizados, errores
    """
    actualizados = 0
    errores = 0

    pricings = db.query(ProductoPricing).filter(ProductoPricing.precio_lista_ml.isnot(None)).all()

    # Pre-fetch real shipping costs for all products in one batch query.
    # Items absent from the dict fall back to ProductoERP.envio (ERP value).
    all_item_ids = [p.item_id for p in pricings]
    envio_real_by_item: Dict[int, float] = resolver_costos_envio_batch(db, all_item_ids)
    costos = costos_ars_actuales(db, all_item_ids, obtener_tipo_cambio_actual(db, "USD"))  # costo SI (S13)

    for pricing in pricings:
        try:
            producto = db.query(ProductoERP).filter(ProductoERP.item_id == pricing.item_id).first()

            if not producto:
                continue

            costo_ars = costos.get(pricing.item_id)
            if not costo_ars:  # unknown cost: never a made-up 0 % markup
                logger.warning(
                    "costo_si pricing: item %s markup %s not recomputed: %s",
                    pricing.item_id,
                    "markup_calculado",
                    SIN_COSTO,
                )
                continue
            grupo_id = obtener_grupo_subcategoria(db, producto.subcategoria_id)
            # Use real shipping cost when available; fall back to ERP envio otherwise.
            costo_envio = envio_real_by_item.get(pricing.item_id)
            if costo_envio is None:
                costo_envio = float(producto.envio or 0)

            markup = _markup_clasica(db, pricing, producto, costo_ars, costo_envio, grupo_id)
            if markup is None:
                continue

            pricing.markup_calculado = markup
            actualizados += 1

        except Exception:
            errores += 1
            continue

    db.commit()
    return {"status": "success", "actualizados": actualizados, "errores": errores}


def _markup_clasica(
    db: Session, pricing: ProductoPricing, producto: ProductoERP, costo_ars: float, costo_envio: float, grupo_id: int
) -> Optional[float]:
    """`markup_calculado` (%) of the stored ML Clásica price over `costo_ars`; None without a list 4 commission."""
    comision_base = obtener_comision_base(db, 4, grupo_id)
    if not comision_base:
        return None
    comisiones = calcular_comision_ml_total(pricing.precio_lista_ml, comision_base, producto.iva, VARIOS_DEFAULT, db=db)
    limpio = calcular_limpio(
        pricing.precio_lista_ml, producto.iva, costo_envio, comisiones["comision_total"], db=db, grupo_id=grupo_id
    )
    return round(calcular_markup(limpio, costo_ars) * 100, 2)


# Stored PVP markups: (price column, pricelist, markup column), as `scripts/recalcular_markups_pricing.py`.
_PVP = (
    ("precio_pvp", 12, "markup_pvp"),
    ("precio_pvp_3_cuotas", 18, "markup_pvp_3_cuotas"),
    ("precio_pvp_6_cuotas", 19, "markup_pvp_6_cuotas"),
    ("precio_pvp_9_cuotas", 20, "markup_pvp_9_cuotas"),
    ("precio_pvp_12_cuotas", 21, "markup_pvp_12_cuotas"),
)

# Every stored markup this recompute owns, with the price it is a markup of.
MARKUPS_GUARDADOS = (
    ("precio_lista_ml", "markup_calculado"),
    ("precio_lista_ml", "markup_rebate"),
    ("precio_lista_ml", "markup_oferta"),
    ("precio_web_transferencia", "markup_web_real"),
) + tuple((precio, markup) for precio, _, markup in _PVP)

SIN_COSTO = "sin_costo"
SIN_TIPO_CAMBIO = "sin_tipo_cambio"
SIN_COMISION = "sin_comision"
SIN_PRECIO = "sin_precio"
SIN_IVA = "sin_iva"

Omitido = Tuple[int, str, str]  # (item_id, markup column or "todos", reason)


def _positivo(valor) -> Optional[float]:
    return float(valor) if valor is not None and float(valor) > 0 else None


def recalcular_markups_guardados(db: Session, item_ids: Iterable[int]) -> List[Omitido]:
    """Rewrite the stored markups of `item_ids` over their current costo SI (owner L15: a costo SI change moves every
    figure computed from it; D4: from the STORED prices, which are never written). Returns what could not be
    recomputed; each one is also logged as a warning with the product, the markup and the reason, never skipped
    silently. Only a database error raises."""
    from app.services.costo_si import lote

    ids = sorted({int(i) for i in item_ids if i is not None})
    filas = (
        db.query(ProductoPricing, ProductoERP)
        .join(ProductoERP, ProductoERP.item_id == ProductoPricing.item_id)
        .filter(ProductoPricing.item_id.in_(ids))
        .all()
        if ids
        else []
    )
    omitidos: List[Omitido] = []

    def omitir(item_id: int, campo: str, motivo: str) -> None:
        logger.warning("costo_si pricing: item %s markup %s not recomputed: %s", item_id, campo, motivo)
        omitidos.append((item_id, campo, motivo))

    if not filas:
        return omitidos
    tipo_cambio = obtener_tipo_cambio_actual(db, "USD")
    costos = lote.actuales(db, [p.item_id for p, _ in filas], tipo_cambio=tipo_cambio)
    envios = resolver_costos_envio_batch(db, [p.item_id for p, _ in filas])
    constantes = obtener_constantes_pricing(db)

    for pricing, producto in filas:
        item_id = pricing.item_id
        costo = costos.get(item_id)
        if costo is None or not costo.costo_ars:
            sin_tasa = costo is not None and costo.costo is not None and costo.moneda == "USD"
            omitir(item_id, "todos", SIN_TIPO_CAMBIO if sin_tasa else SIN_COSTO)
            continue
        if producto.iva is None:
            omitir(item_id, "todos", SIN_IVA)  # every net price divides by the VAT: nothing to recompute with
            continue
        costo_ars = float(costo.costo_ars)
        envio = envios.get(item_id)
        envio = float(producto.envio or 0) if envio is None else envio
        grupo_id = obtener_grupo_subcategoria(db, producto.subcategoria_id)

        for precio_col, markup_col in MARKUPS_GUARDADOS:
            if _positivo(getattr(pricing, precio_col)) is None and getattr(pricing, markup_col) is not None:
                omitir(item_id, markup_col, SIN_PRECIO)  # a markup left without its price: nothing to recompute

        if _positivo(pricing.precio_lista_ml) is not None:
            markup = _markup_clasica(db, pricing, producto, costo_ars, envio, grupo_id)
            if markup is None:
                omitir(item_id, "markup_calculado", SIN_COMISION)
            else:
                pricing.markup_calculado = markup
            pricing.markup_rebate = calcular_markup_rebate(
                db, producto, pricing, tipo_cambio, costo_envio=envio, costo_ars=costo_ars
            )
            pricing.markup_oferta = calcular_markup_oferta(
                db, producto, tipo_cambio, costo_envio=envio, costo_ars=costo_ars
            )

        precio_web = _positivo(pricing.precio_web_transferencia)
        if precio_web is not None:
            limpio = limpio_web_transferencia(
                precio_web, producto.iva, constantes["comision_tienda_nube"], constantes["varios"]
            )
            pricing.markup_web_real = round((limpio - costo_ars) / costo_ars * 100, 2)

        for precio_col, pricelist_id, markup_col in _PVP:
            precio = _positivo(getattr(pricing, precio_col))
            if precio is None:
                continue
            comision_base = obtener_comision_base(db, pricelist_id, grupo_id)
            if not comision_base:
                omitir(item_id, markup_col, SIN_COMISION)
                continue
            comisiones = calcular_comision_ml_total(precio, comision_base, producto.iva, db=db, constantes=constantes)
            limpio = calcular_limpio(
                precio, producto.iva, envio, comisiones["comision_total"], db=db, grupo_id=grupo_id
            )
            setattr(pricing, markup_col, round(calcular_markup(limpio, costo_ars) * 100, 2))
    db.flush()
    return omitidos
