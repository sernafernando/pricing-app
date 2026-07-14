"""
Productos - Detail endpoints.

Handles product detail view, MercadoLibre data (lazy), and active offers.
"""

from fastapi import APIRouter, Depends, HTTPException
from sqlalchemy.orm import Session
from sqlalchemy import func, and_, cast, Date
from datetime import UTC, datetime, date, timedelta
from app.core.database import get_db, get_async_db
from app.models.producto import ProductoERP, ProductoPricing
from app.models.usuario import Usuario
from app.api.deps import get_current_user
from app.services.envio_real_service import resolver_costo_envio

import logging

logger = logging.getLogger(__name__)

router = APIRouter()


@router.get("/productos/{item_id}/detalle")
def obtener_detalle_producto(
    item_id: int, db: Session = Depends(get_db), current_user: Usuario = Depends(get_current_user)
):
    """Obtiene información detallada de un producto (sin datos de ML - se cargan lazy)"""
    from app.services.pricing_calculator import (
        obtener_tipo_cambio_actual,
        obtener_comision_base,
        obtener_grupo_subcategoria,
    )

    # Producto base
    producto = db.query(ProductoERP).filter(ProductoERP.item_id == item_id).first()
    if not producto:
        raise HTTPException(status_code=404, detail="Producto no encontrado")

    # Pricing
    pricing = db.query(ProductoPricing).filter(ProductoPricing.item_id == item_id).first()

    # Obtener tipo de cambio
    tipo_cambio = obtener_tipo_cambio_actual(db, "USD")

    # Costo en ARS
    costo_ars = (
        float(producto.costo) * tipo_cambio if producto.moneda_costo == "USD" and tipo_cambio else float(producto.costo)
    )

    # Obtener comisión ML para lista clásica
    grupo_id = obtener_grupo_subcategoria(db, producto.subcategoria_id)
    comision_clasica = obtener_comision_base(db, 1, grupo_id) if grupo_id else None

    # Costo de envío — resolved from mlwebhook DB (falls back to ERP on any error)
    costo_envio = resolver_costo_envio(db, producto)

    # ML data ahora se carga de forma lazy en el endpoint separado /mercadolibre
    # Esto mejora significativamente el tiempo de carga del modal

    # Obtener últimas 5 compras del producto (puco_id = 10)
    from app.models.tb_supplier import TBSupplier
    from app.models.commercial_transaction import CommercialTransaction
    from app.models.item_transaction import ItemTransaction

    ultimas_compras_query = (
        db.query(
            TBSupplier.supp_name,
            ItemTransaction.it_cd,
            ItemTransaction.it_qty,
            ItemTransaction.it_price,
            ItemTransaction.curr_id,
        )
        .join(
            CommercialTransaction,
            and_(
                CommercialTransaction.comp_id == ItemTransaction.comp_id,
                CommercialTransaction.ct_transaction == ItemTransaction.ct_transaction,
            ),
        )
        .join(
            TBSupplier,
            and_(
                TBSupplier.comp_id == CommercialTransaction.comp_id, TBSupplier.supp_id == CommercialTransaction.supp_id
            ),
        )
        .filter(
            and_(
                ItemTransaction.puco_id == 10,  # Compras
                ItemTransaction.item_id == item_id,
                CommercialTransaction.supp_id.isnot(None),
            )
        )
        .order_by(ItemTransaction.it_cd.desc())
        .limit(5)
        .all()
    )

    ultimas_compras = []
    for compra in ultimas_compras_query:
        ultimas_compras.append(
            {
                "proveedor": compra.supp_name,
                "fecha": compra.it_cd.isoformat() if compra.it_cd else None,
                "cantidad": float(compra.it_qty) if compra.it_qty else 0,
                "precio_unitario": float(compra.it_price) if compra.it_price else 0,
                "moneda_id": compra.curr_id,
            }
        )

    return {
        "producto": {
            "item_id": producto.item_id,
            "codigo": producto.codigo,
            "descripcion": producto.descripcion,
            "marca": producto.marca,
            "categoria": producto.categoria,
            "subcategoria_id": producto.subcategoria_id,
            "stock": producto.stock,
            "moneda_costo": producto.moneda_costo,
            "costo": float(producto.costo),
            "costo_ars": costo_ars,
            "iva": float(producto.iva),
            "costo_envio": costo_envio,
            "tipo_cambio_usado": tipo_cambio,
        },
        "pricing": {
            "precio_lista_ml": float(pricing.precio_lista_ml) if pricing and pricing.precio_lista_ml else None,
            "markup": float(pricing.markup_calculado) if pricing and pricing.markup_calculado else None,
            "comision_ml_porcentaje": comision_clasica,
            "participa_rebate": pricing.participa_rebate if pricing else False,
            "porcentaje_rebate": float(pricing.porcentaje_rebate) if pricing and pricing.porcentaje_rebate else None,
            "out_of_cards": pricing.out_of_cards if pricing else False,
            "participa_web_transferencia": pricing.participa_web_transferencia if pricing else False,
            "porcentaje_markup_web": float(pricing.porcentaje_markup_web)
            if pricing and pricing.porcentaje_markup_web
            else None,
            "precio_web_transferencia": float(pricing.precio_web_transferencia)
            if pricing and pricing.precio_web_transferencia
            else None,
            "markup_web_real": float(pricing.markup_web_real) if pricing and pricing.markup_web_real else None,
            "precio_3_cuotas": float(pricing.precio_3_cuotas) if pricing and pricing.precio_3_cuotas else None,
            "precio_6_cuotas": float(pricing.precio_6_cuotas) if pricing and pricing.precio_6_cuotas else None,
            "precio_9_cuotas": float(pricing.precio_9_cuotas) if pricing and pricing.precio_9_cuotas else None,
            "precio_12_cuotas": float(pricing.precio_12_cuotas) if pricing and pricing.precio_12_cuotas else None,
            "usuario_modifico": pricing.usuario.nombre if pricing and pricing.usuario else None,
            "fecha_modificacion": pricing.fecha_modificacion if pricing else None,
        },
        "ultimas_compras": ultimas_compras,
        # ventas, precios_ml, y publicaciones_ml ahora se cargan de forma lazy en /mercadolibre endpoint
    }


@router.get("/productos/{item_id}/mercadolibre")
async def obtener_datos_ml_producto(
    item_id: int,
    db: Session = Depends(get_async_db),
    current_user: Usuario = Depends(get_current_user),
    lite: bool = False,
):
    """Obtiene solo los datos de MercadoLibre de un producto (lazy loading)

    `lite=True` skips the live ml-webhook enrichment (`get_items_batch`) and
    returns only the persisted fields (mla, lista_nombre, pricelist_id,
    publication_status, persisted precios). Used by the promotions panel,
    which never reads the live-enriched extras (precio_ml, catalog_product_id).
    Default (`lite=False`) preserves the full response for existing callers
    (e.g. ModalInfoProducto).
    """
    from app.models.publicacion_ml import PublicacionML
    from app.services.ml_webhook_client import ml_webhook_client
    from sqlalchemy import text

    # Obtener todas las publicaciones ML del item
    publicaciones_ml_query = (
        db.query(PublicacionML).filter(PublicacionML.item_id == item_id, PublicacionML.activo == True).all()
    )

    # Crear diccionario base de publicaciones
    publicaciones_dict = {}
    mla_ids = []

    for pub in publicaciones_ml_query:
        publicaciones_dict[pub.mla] = {
            "mla": pub.mla,
            "titulo": pub.item_title,
            "lista_nombre": pub.lista_nombre,
            "pricelist_id": pub.pricelist_id,
            "precio_ml": None,
            "precios": [],
        }
        mla_ids.append(pub.mla)

    # Obtener precios de ML para estas publicaciones
    if mla_ids:
        precios_ml_data = db.execute(
            text("""
                SELECT pricelist_id, precio, mla
                FROM precios_ml
                WHERE item_id = :item_id AND mla = ANY(:mla_ids)
            """),
            {"item_id": item_id, "mla_ids": mla_ids},
        ).fetchall()

        for pricelist_id, precio, mla in precios_ml_data:
            if mla and mla in publicaciones_dict:
                publicaciones_dict[mla]["precios"].append(
                    {"pricelist_id": pricelist_id, "precio": float(precio) if precio else None}
                )

    # Obtener datos de ML via webhook service (live call — skipped in `lite` mode,
    # which the promotions panel uses since it only needs persisted fields)
    if mla_ids and not lite:
        try:
            ml_items = await ml_webhook_client.get_items_batch(mla_ids)
            for mla_id, ml_data in ml_items.items():
                if mla_id in publicaciones_dict:
                    publicaciones_dict[mla_id]["precio_ml"] = (
                        float(ml_data.get("price", 0)) if ml_data.get("price") else None
                    )
                    publicaciones_dict[mla_id]["catalog_product_id"] = ml_data.get("catalog_product_id")
        except Exception as e:
            logger.error(f"Error consultando ml-webhook: {e}")
            pass

    # Obtener status de catálogo desde la BD
    if mla_ids:
        catalog_statuses = db.execute(
            text("""
            SELECT mla, catalog_product_id, status, price_to_win, winner_mla, winner_price
            FROM v_ml_catalog_status_latest
            WHERE mla = ANY(:mla_ids)
        """),
            {"mla_ids": mla_ids},
        ).fetchall()

        for row in catalog_statuses:
            mla, catalog_id, status, ptw, winner, winner_price = row
            if mla in publicaciones_dict:
                publicaciones_dict[mla]["catalog_status"] = status
                publicaciones_dict[mla]["catalog_price_to_win"] = float(ptw) if ptw else None
                publicaciones_dict[mla]["catalog_winner_mla"] = winner
                publicaciones_dict[mla]["catalog_winner_price"] = float(winner_price) if winner_price else None

    # Obtener estado de las publicaciones
    if mla_ids:
        pub_statuses = db.execute(
            text("""
            SELECT mlp_publicationid, mlp_laststatusid, mlp_active
            FROM tb_mercadolibre_items_publicados
            WHERE mlp_publicationid = ANY(:mla_ids)
        """),
            {"mla_ids": mla_ids},
        ).fetchall()

        for mla, status_id, is_active in pub_statuses:
            if mla in publicaciones_dict:
                if status_id:
                    status_map = {153: "active", 154: "paused", 155: "closed", 156: "under_review"}
                    publicaciones_dict[mla]["publication_status"] = status_map.get(status_id, f"status_{status_id}")
                elif is_active is not None:
                    publicaciones_dict[mla]["publication_status"] = "active" if is_active else "paused"
                else:
                    publicaciones_dict[mla]["publication_status"] = None

    # Calcular ventas de los últimos 7, 15 y 30 días
    # Usamos MLVentaMetrica (misma fuente que el dashboard)
    from app.models.ml_venta_metrica import MLVentaMetrica

    fecha_actual = datetime.now(UTC).date()
    ventas_stats = {}

    for dias in [7, 15, 30]:
        fecha_desde = fecha_actual - timedelta(days=dias)
        fecha_hasta_ajustada = fecha_actual + timedelta(days=1)

        # Query usando MLVentaMetrica (misma fuente que dashboard)
        # Usar cast(fecha_venta as Date) para comparar solo fechas (fecha_venta es DateTime)
        ventas_ml = (
            db.query(
                func.count(MLVentaMetrica.id).label("numero_ventas"),
                func.coalesce(func.sum(MLVentaMetrica.cantidad), 0).label("cantidad_vendida"),
                func.coalesce(func.sum(MLVentaMetrica.monto_total), 0).label("monto_total"),
            )
            .filter(
                MLVentaMetrica.item_id == item_id,
                cast(MLVentaMetrica.fecha_venta, Date) >= fecha_desde,
                cast(MLVentaMetrica.fecha_venta, Date) < fecha_hasta_ajustada,
            )
            .first()
        )

        ventas_stats[f"ultimos_{dias}_dias"] = {
            "cantidad_vendida": int(ventas_ml.cantidad_vendida or 0),
            "monto_total": float(ventas_ml.monto_total or 0),
            "numero_ventas": int(ventas_ml.numero_ventas or 0),
        }

    return {
        "publicaciones_ml": sorted(
            publicaciones_dict.values(),
            key=lambda x: ({4: 0, 17: 1, 14: 2, 13: 3, 23: 4}.get(x.get("pricelist_id"), 999), x.get("mla", "")),
        ),
        "ventas": ventas_stats,
    }


@router.get("/productos/{item_id}/ofertas-vigentes")
def obtener_ofertas_vigentes(
    item_id: int, db: Session = Depends(get_db), current_user: Usuario = Depends(get_current_user)
):
    from app.models.publicacion_ml import PublicacionML
    from app.models.oferta_ml import OfertaML
    from app.services.pricing_calculator import (
        obtener_tipo_cambio_actual,
        convertir_a_pesos,
        obtener_grupo_subcategoria,
        obtener_comision_base,
        calcular_comision_ml_total,
        calcular_limpio,
        calcular_markup,
    )

    producto = db.query(ProductoERP).filter(ProductoERP.item_id == item_id).first()
    if not producto:
        return {"item_id": item_id, "publicaciones": []}

    tipo_cambio = None
    if producto.moneda_costo == "USD":
        tipo_cambio = obtener_tipo_cambio_actual(db, "USD")
    costo_ars = convertir_a_pesos(producto.costo, producto.moneda_costo, tipo_cambio)

    # Resolve shipping cost once via central resolver (mlwebhook first, ERP fallback)
    costo_envio_oferta = resolver_costo_envio(db, producto)

    publicaciones = db.query(PublicacionML).filter(PublicacionML.item_id == item_id).all()
    if not publicaciones:
        return {"item_id": item_id, "publicaciones": []}

    hoy = date.today()
    resultado = []

    for pub in publicaciones:
        oferta = (
            db.query(OfertaML)
            .filter(OfertaML.mla == pub.mla, OfertaML.fecha_desde <= hoy, OfertaML.fecha_hasta >= hoy)
            .first()
        )

        markup_oferta = None
        if oferta and oferta.pvp_seller and oferta.pvp_seller > 0:
            grupo_id = obtener_grupo_subcategoria(db, producto.subcategoria_id)
            comision_base = obtener_comision_base(db, pub.pricelist_id, grupo_id)

            if comision_base:
                comisiones = calcular_comision_ml_total(oferta.pvp_seller, comision_base, producto.iva, db=db)
                limpio = calcular_limpio(
                    oferta.pvp_seller,
                    producto.iva,
                    costo_envio_oferta,
                    comisiones["comision_total"],
                    db=db,
                    grupo_id=grupo_id,
                )
                markup_oferta = round(calcular_markup(limpio, costo_ars) * 100, 2)

        resultado.append(
            {
                "mla": pub.mla,
                "item_title": pub.item_title,
                "pricelist_id": pub.pricelist_id,
                "lista_nombre": pub.lista_nombre,
                "tiene_oferta": oferta is not None,
                "oferta": {
                    "precio_final": oferta.precio_final,
                    "pvp_seller": oferta.pvp_seller,
                    "markup_oferta": markup_oferta,
                    "aporte_meli_pesos": oferta.aporte_meli_pesos,
                    "aporte_meli_porcentaje": oferta.aporte_meli_porcentaje,
                    "fecha_desde": oferta.fecha_desde.isoformat(),
                    "fecha_hasta": oferta.fecha_hasta.isoformat(),
                }
                if oferta
                else None,
            }
        )

    return {
        "item_id": item_id,
        "total_publicaciones": len(resultado),
        "con_oferta": sum(1 for r in resultado if r["tiene_oferta"]),
        "publicaciones": resultado,
    }
