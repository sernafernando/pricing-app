"""
Script para calcular y almacenar markup_rebate y markup_oferta en productos_pricing

Ejecutar desde el directorio backend:
    cd /var/www/html/pricing-app/backend
    python -m app.scripts.calcular_markups_rebate_oferta
"""

import sys
import os

if __name__ == "__main__":
    backend_path = os.path.dirname(os.path.dirname(os.path.dirname(os.path.abspath(__file__))))
    if backend_path not in sys.path:
        sys.path.insert(0, backend_path)

from sqlalchemy.orm import Session
from app.core.database import SessionLocal
import app.models
from app.models.producto import ProductoERP, ProductoPricing
from app.models.publicacion_ml import PublicacionML
from app.models.oferta_ml import OfertaML
from app.services.envio_real_service import resolver_costos_envio_batch
from app.services.pricing_calculator import (
    obtener_tipo_cambio_actual,
    convertir_a_pesos,
    obtener_grupo_subcategoria,
    obtener_comision_base,
    calcular_comision_ml_total,
    calcular_limpio,
    calcular_markup,
)
from datetime import date


def calcular_markups(db: Session):
    """
    Calcula y almacena markup_rebate y markup_oferta para todos los productos
    """

    print("🚀 Iniciando cálculo de markups rebate y oferta\n")

    hoy = date.today()

    # Obtener todos los productos con pricing
    productos = (
        db.query(ProductoERP, ProductoPricing)
        .outerjoin(ProductoPricing, ProductoERP.item_id == ProductoPricing.item_id)
        .filter(ProductoPricing.item_id.isnot(None))
        .all()
    )

    total_productos = len(productos)
    print(f"📊 Procesando {total_productos} productos\n")

    # Pre-fetch real shipping costs for all products in one batch query.
    # Items absent from the dict fall back to ProductoERP.envio (ERP value).
    rebate_item_ids = [p_erp.item_id for p_erp, _ in productos]
    envio_real_by_item: dict[int, float] = resolver_costos_envio_batch(db, rebate_item_ids)

    actualizados_rebate = 0
    actualizados_oferta = 0
    errores = 0

    for i, (producto_erp, producto_pricing) in enumerate(productos, 1):
        try:
            markup_rebate_val = None
            markup_oferta_val = None

            # Resolve real shipping cost: batch resolver takes priority over ERP envio.
            costo_envio = envio_real_by_item.get(producto_erp.item_id)
            if costo_envio is None:
                costo_envio = float(producto_erp.envio or 0)

            # ========== CALCULAR MARKUP REBATE ==========
            if producto_pricing.participa_rebate and producto_pricing.precio_lista_ml and producto_erp.costo:
                try:
                    porcentaje_rebate_val = float(
                        producto_pricing.porcentaje_rebate if producto_pricing.porcentaje_rebate is not None else 3.8
                    )
                    precio_rebate = float(producto_pricing.precio_lista_ml) / (1 - porcentaje_rebate_val / 100)

                    # Calcular markup completo considerando comisiones
                    tipo_cambio_rebate = None
                    if producto_erp.moneda_costo == "USD":
                        tipo_cambio_rebate = obtener_tipo_cambio_actual(db, "USD")

                    costo_rebate = convertir_a_pesos(producto_erp.costo, producto_erp.moneda_costo, tipo_cambio_rebate)
                    grupo_id_rebate = obtener_grupo_subcategoria(db, producto_erp.subcategoria_id)
                    comision_base_rebate = obtener_comision_base(db, 4, grupo_id_rebate)

                    if comision_base_rebate and precio_rebate > 0:
                        comisiones_rebate = calcular_comision_ml_total(
                            precio_rebate, comision_base_rebate, producto_erp.iva, db=db
                        )
                        limpio_rebate = calcular_limpio(
                            precio_rebate,
                            producto_erp.iva,
                            costo_envio,
                            comisiones_rebate["comision_total"],
                            db=db,
                            grupo_id=grupo_id_rebate,
                        )
                        markup_rebate_val = calcular_markup(limpio_rebate, costo_rebate) * 100
                        actualizados_rebate += 1
                except Exception as e:
                    pass

            # ========== CALCULAR MARKUP OFERTA ==========
            if producto_erp.costo:
                try:
                    # Buscar publicación del producto
                    pubs = db.query(PublicacionML).filter(PublicacionML.item_id == producto_erp.item_id).all()

                    mejor_oferta = None
                    mejor_pub = None

                    for pub in pubs:
                        # Buscar oferta vigente para esta publicación
                        oferta = (
                            db.query(OfertaML)
                            .filter(
                                OfertaML.mla == pub.mla,
                                OfertaML.fecha_desde <= hoy,
                                OfertaML.fecha_hasta >= hoy,
                                OfertaML.pvp_seller.isnot(None),
                            )
                            .order_by(OfertaML.fecha_desde.desc())
                            .first()
                        )

                        if oferta:
                            if not mejor_oferta:
                                mejor_oferta = oferta
                                mejor_pub = pub

                    if mejor_oferta and mejor_pub:
                        mejor_oferta_pvp = float(mejor_oferta.pvp_seller) if mejor_oferta.pvp_seller else None

                        if mejor_oferta_pvp and mejor_oferta_pvp > 0:
                            tipo_cambio_oferta = None
                            if producto_erp.moneda_costo == "USD":
                                tipo_cambio_oferta = obtener_tipo_cambio_actual(db, "USD")

                            costo_oferta = convertir_a_pesos(
                                producto_erp.costo, producto_erp.moneda_costo, tipo_cambio_oferta
                            )
                            grupo_id_oferta = obtener_grupo_subcategoria(db, producto_erp.subcategoria_id)
                            comision_base_oferta = obtener_comision_base(db, mejor_pub.pricelist_id, grupo_id_oferta)

                            if comision_base_oferta:
                                comisiones_oferta = calcular_comision_ml_total(
                                    mejor_oferta_pvp, comision_base_oferta, producto_erp.iva, db=db
                                )
                                limpio_oferta = calcular_limpio(
                                    mejor_oferta_pvp,
                                    producto_erp.iva,
                                    costo_envio,
                                    comisiones_oferta["comision_total"],
                                    db=db,
                                    grupo_id=grupo_id_oferta,
                                )
                                markup_oferta_val = calcular_markup(limpio_oferta, costo_oferta) * 100
                                actualizados_oferta += 1
                except Exception as e:
                    pass

            # Actualizar en BD
            producto_pricing.markup_rebate = markup_rebate_val
            producto_pricing.markup_oferta = markup_oferta_val

            # Commit cada 100 registros
            if i % 100 == 0:
                db.commit()
                print(f"   ✓ {i}/{total_productos} productos procesados...")

        except Exception as e:
            errores += 1
            print(f"   ⚠️  Error procesando item_id {producto_erp.item_id}: {str(e)}")
            db.rollback()
            continue

    # Commit final
    db.commit()

    print("\n✅ Cálculo completado!")
    print(f"   Markups rebate calculados: {actualizados_rebate}")
    print(f"   Markups oferta calculados: {actualizados_oferta}")
    print(f"   Errores: {errores}")


if __name__ == "__main__":
    db = SessionLocal()
    try:
        calcular_markups(db)
    finally:
        db.close()
