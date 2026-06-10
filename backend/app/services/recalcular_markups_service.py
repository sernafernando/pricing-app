"""
Service para recalcular markups de todos los productos con precio.

Extraído del endpoint /recalcular-markups para poder ejecutarse
tanto desde la API como desde scripts standalone.
"""

from typing import Dict

from sqlalchemy.orm import Session

from app.models.producto import ProductoERP, ProductoPricing
from app.services.envio_real_service import resolver_costos_envio_batch
from app.services.pricing_calculator import (
    VARIOS_DEFAULT,
    calcular_comision_ml_total,
    calcular_limpio,
    calcular_markup,
    convertir_a_pesos,
    obtener_comision_base,
    obtener_grupo_subcategoria,
    obtener_tipo_cambio_actual,
)


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

    for pricing in pricings:
        try:
            producto = db.query(ProductoERP).filter(ProductoERP.item_id == pricing.item_id).first()

            if not producto:
                continue

            tipo_cambio = None
            if producto.moneda_costo == "USD":
                tipo_cambio = obtener_tipo_cambio_actual(db, "USD")

            costo_ars = convertir_a_pesos(producto.costo, producto.moneda_costo, tipo_cambio)
            grupo_id = obtener_grupo_subcategoria(db, producto.subcategoria_id)
            comision_base = obtener_comision_base(db, 4, grupo_id)

            if not comision_base:
                continue

            # Use real shipping cost when available; fall back to ERP envio otherwise.
            costo_envio = envio_real_by_item.get(pricing.item_id)
            if costo_envio is None:
                costo_envio = float(producto.envio or 0)

            comisiones = calcular_comision_ml_total(
                pricing.precio_lista_ml,
                comision_base,
                producto.iva,
                VARIOS_DEFAULT,
                db=db,
            )
            limpio = calcular_limpio(
                pricing.precio_lista_ml,
                producto.iva,
                costo_envio,
                comisiones["comision_total"],
                db=db,
                grupo_id=grupo_id,
            )
            markup = calcular_markup(limpio, costo_ars)

            pricing.markup_calculado = round(markup * 100, 2)
            actualizados += 1

        except Exception:
            errores += 1
            continue

    db.commit()
    return {"status": "success", "actualizados": actualizados, "errores": errores}
