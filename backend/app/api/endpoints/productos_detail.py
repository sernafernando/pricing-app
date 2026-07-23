"""
Productos - Detail endpoints.

Handles product detail view, MercadoLibre data (lazy), and active offers.
"""

from typing import Optional

from fastapi import APIRouter, Depends, HTTPException
from sqlalchemy.exc import SQLAlchemyError
from sqlalchemy.orm import Session
from sqlalchemy import func, and_, cast, Date
from datetime import UTC, datetime, date, timedelta
from app.core.database import get_db, get_async_db
from app.models.producto import ProductoERP, ProductoPricing
from app.models.usuario import Usuario
from app.api.deps import get_current_user
from app.services.envio_real_service import resolver_costo_envio
from app.services.ml_promotions_service import (
    fetch_mlas_with_active_promo_type,
    fetch_mlas_with_candidate_only,
    fetch_mlas_with_candidate_only_for_types,
    fetch_mlas_with_started,
    fetch_promo_node_summary_by_mla,
    fetch_promo_summary_by_mla,
)
from app.services.promo_filter_resolver import PromoResolverFns, select_promo_resolver
from app.services.ml_publication_link_service import lazy_fill_links
from app.services.ml_publication_status_service import resolve_publication_status
from app.services.ml_publication_tree_service import assemble_publication_tree
from app.schemas.productos_tree import ProductTreeResponse
from fastapi.concurrency import run_in_threadpool

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
    promo_tipos: Optional[str] = None,
    promo_estado: Optional[str] = None,
    con_promo_aplicada: Optional[bool] = None,
    con_promo_sin_aplicar: Optional[bool] = None,
):
    """Obtiene solo los datos de MercadoLibre de un producto (lazy loading)

    `lite=True` skips the live ml-webhook enrichment (`get_items_batch`) and
    returns only the persisted fields (mla, lista_nombre, pricelist_id,
    publication_status, persisted precios). Used by the promotions panel,
    which never reads the live-enriched extras (precio_ml, catalog_product_id).
    Default (`lite=False`) preserves the full response for existing callers
    (e.g. ModalInfoProducto).

    `promo_tipos`/`promo_estado`/`con_promo_aplicada`/`con_promo_sin_aplicar`
    (feature productos-promo-filter-per-mla) mirror the Productos LISTADO's
    promo filter params. When any is active, each publication in the response
    gets a per-MLA `matches_filter: bool` field, computed via the SAME
    `select_promo_resolver` dispatch as the list endpoint (single source of
    truth — spec: "Single source of truth for MLA-set resolution"), bounded
    by this product's own `mla_ids` (never the full account universe).

    Fail-OPEN on cross-DB unavailability (UNLIKE the list endpoint's 503
    fail-closed): `matches_filter` is left absent (shows all, degrades
    gracefully) — consistent with this endpoint's existing enrichment
    degradation pattern (e.g. `fetch_promo_summary_by_mla` above).
    """
    # Validate promo_estado identically to the LISTADO endpoint so both call
    # sites of select_promo_resolver reject the same inputs (single source of
    # truth): an unrecognized value must 422, not silently degrade to
    # `disponible` semantics via the resolver's `applied_only` fallback.
    if promo_estado is not None and promo_estado not in ("disponible", "aplicada", "sin_aplicar"):
        raise HTTPException(
            status_code=422,
            detail="promo_estado inválido: debe ser 'disponible', 'aplicada' o 'sin_aplicar'",
        )

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

    # Enriquecer con resumen de promos activas (batched, cross-DB, read-only).
    # Enrichment nunca debe romper la lista de publicaciones: cualquier falla
    # (incl. ML_WEBHOOK_DB_URL no configurada) se loguea y los campos quedan
    # ausentes en las publicaciones afectadas.
    if mla_ids:
        try:
            promo_summary = await run_in_threadpool(fetch_promo_summary_by_mla, mla_ids)
        except Exception as e:
            logger.warning(f"Error obteniendo resumen de promos: {e}")
            promo_summary = {}

        for mla, summary in promo_summary.items():
            if mla in publicaciones_dict:
                publicaciones_dict[mla]["promo_active_count"] = summary.get("active_count", 0)
                publicaciones_dict[mla]["promo_has_applied"] = summary.get("has_applied", False)
                publicaciones_dict[mla]["promo_applied_name"] = summary.get("applied_name")

    # matches_filter por publicación (feature productos-promo-filter-per-mla):
    # reusa select_promo_resolver (mismo dispatch que el LISTADO) acotado a
    # las mla_ids de ESTE producto. Fail-OPEN: cualquier falla del cross-DB
    # deja matches_filter ausente (nunca 503, nunca oculta publicaciones).
    tipos_list = [t.strip() for t in promo_tipos.split(",") if t.strip()] if promo_tipos else []
    resolver_entry = select_promo_resolver(
        PromoResolverFns(
            active_promo_type=fetch_mlas_with_active_promo_type,
            started=fetch_mlas_with_started,
            candidate_only=fetch_mlas_with_candidate_only,
            candidate_only_for_types=fetch_mlas_with_candidate_only_for_types,
        ),
        tipos_list or None,
        promo_estado,
        con_promo_aplicada,
        con_promo_sin_aplicar,
        mla_ids=mla_ids or None,
    )
    if resolver_entry and mla_ids:
        resolver, log_context = resolver_entry
        try:
            matching_mlas = await run_in_threadpool(resolver)
        except (RuntimeError, SQLAlchemyError) as exc:
            logger.warning("%s no disponible (lite matches_filter): %s", log_context, exc)
        else:
            for mla in mla_ids:
                publicaciones_dict[mla]["matches_filter"] = mla in matching_mlas

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

    # Obtener estado de las publicaciones. El mapeo status_id/is_active ->
    # etiqueta vive en `ml_publication_status_service.resolve_publication_status`
    # (misma fuente que el árbol recursivo, así ambas vistas nunca muestran
    # estados distintos). Solo se asigna `publication_status` a las MLAs
    # presentes en la tabla: una MLA ausente no recibe la clave.
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
                publicaciones_dict[mla]["publication_status"] = resolve_publication_status(status_id, is_active)

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


@router.get("/productos/{item_id}/mercadolibre/tree", response_model=ProductTreeResponse)
def obtener_arbol_ml_producto(
    item_id: int,
    db: Session = Depends(get_db),
    current_user: Usuario = Depends(get_current_user),
    promo_tipos: Optional[str] = None,
    promo_estado: Optional[str] = None,
    con_promo_aplicada: Optional[bool] = None,
    con_promo_sin_aplicar: Optional[bool] = None,
) -> ProductTreeResponse:
    """Assembles the recursive product/family/catalog/vinculada publication
    tree for `item_id` (productos-catalog-family-tree PR2).

    Sibling to the existing flat `GET /productos/{item_id}/mercadolibre`
    endpoint, which is kept UNCHANGED for existing callers — this is a
    NEW route, not a replacement.

    Hybrid lazy-fill (design's cold-start decision): before assembling
    the tree, calls `lazy_fill_links`, which pool-safely tops up
    stale/missing `ml_publication_links` rows from the ML `render`
    payload. `lazy_fill_links` NEVER uses this endpoint's request `db`
    session for the HTTP round-trip (pool-exhaustion fix — see
    `ml_publication_link_service.py`) and NEVER raises: any failure
    (ml-webhook proxy down, network error, lock contention, etc.)
    degrades silently to whatever `ml_publication_links`/
    `ml_item_relations` data already persisted (fail-open, matches the
    flat endpoint's existing degradation pattern).

    `matches_filter` reuses the exact same `select_promo_resolver`
    dispatch as the flat endpoint, bounded to this product's own MLAs,
    fail-open on cross-DB failure (field simply absent, never hides
    nodes, never 503s).
    """
    if promo_estado is not None and promo_estado not in ("disponible", "aplicada", "sin_aplicar"):
        raise HTTPException(
            status_code=422,
            detail="promo_estado inválido: debe ser 'disponible', 'aplicada' o 'sin_aplicar'",
        )

    from app.models.publicacion_ml import PublicacionML

    mla_ids = [
        row.mla
        for row in db.query(PublicacionML).filter(PublicacionML.item_id == item_id, PublicacionML.activo == True).all()
    ]

    # Hybrid lazy-fill: top up stale/missing link rows before assembling.
    # `lazy_fill_links` never touches this request's `db` session (pool-
    # safety) and never raises (fail-open) — the tree degrades to
    # whatever is already persisted if the fill can't complete.
    if mla_ids:
        lazy_fill_links(mla_ids, item_id)

    # matches_filter (mismo dispatch que el endpoint flat, acotado a este producto).
    tipos_list = [t.strip() for t in promo_tipos.split(",") if t.strip()] if promo_tipos else []
    resolver_entry = select_promo_resolver(
        PromoResolverFns(
            active_promo_type=fetch_mlas_with_active_promo_type,
            started=fetch_mlas_with_started,
            candidate_only=fetch_mlas_with_candidate_only,
            candidate_only_for_types=fetch_mlas_with_candidate_only_for_types,
        ),
        tipos_list or None,
        promo_estado,
        con_promo_aplicada,
        con_promo_sin_aplicar,
        mla_ids=mla_ids or None,
    )

    matches_filter_by_mla: Optional[dict] = None
    if resolver_entry and mla_ids:
        resolver, log_context = resolver_entry
        try:
            matching_mlas = resolver()
        except (RuntimeError, SQLAlchemyError) as exc:
            logger.warning("%s no disponible (tree matches_filter): %s", log_context, exc)
        else:
            matches_filter_by_mla = {mla: mla in matching_mlas for mla in mla_ids}

    # Collapsed-node promo summary (catalog-tree-node-summary PR): ONE
    # batched cross-DB fetch for every MLA in this product's tree (mirrors
    # the matches_filter dispatch above — no N+1 per node). Fail-open: any
    # failure (ML_WEBHOOK_DB_URL unset, mlwebhook down) leaves the summary
    # absent and the tree still returns 200, never 500/503.
    promo_summary_by_mla: Optional[dict] = None
    if mla_ids:
        try:
            promo_summary_by_mla = fetch_promo_node_summary_by_mla(mla_ids)
        except (RuntimeError, SQLAlchemyError) as exc:
            logger.warning("fetch_promo_node_summary_by_mla no disponible (tree promo_summary): %s", exc)

    result = assemble_publication_tree(
        db,
        item_id=item_id,
        matches_filter_by_mla=matches_filter_by_mla,
        promo_summary_by_mla=promo_summary_by_mla,
    )
    return result


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
