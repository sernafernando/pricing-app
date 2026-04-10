"""
Endpoints de enrichment, geocodificación e impresión de etiquetas ZPL.

Incluye:
- POST /etiquetas-envio/re-enriquecer (re-enrichment batch)
- POST /etiquetas-envio/geocodificar (geocodificación masiva)
- POST /etiquetas-envio/{shipping_id}/geocodificar (geocodificación individual)
- GET /etiquetas-envio/{shipping_id}/etiqueta (ZPL desde ML)
- GET /etiquetas-envio/{shipping_id}/etiqueta-manual (ZPL local para manuales)
"""

import json
import logging
from datetime import date
from pathlib import Path as FilePath
from typing import Optional

from fastapi import APIRouter, Depends, HTTPException, Query
from fastapi.responses import Response
from sqlalchemy import and_, func
from sqlalchemy.orm import Session

from app.core.database import get_db
from app.core.sse import sse_publish_bg
from app.api.deps import get_current_user
from app.models.usuario import Usuario
from app.models.etiqueta_envio import EtiquetaEnvio
from app.models.logistica import Logistica
from app.models.transporte import Transporte
from app.models.mercadolibre_order_shipping import MercadoLibreOrderShipping
from app.models.sale_order_detail import SaleOrderDetail
from app.models.tb_item import TBItem
from app.services.etiqueta_enrichment_service import (
    re_enriquecer_desde_db,
    re_enriquecer_por_http,
)
from app.services.ml_webhook_service import fetch_shipment_label_zpl
from app.services.geocoding_service import geocode_address

from app.api.endpoints.etiquetas_shared import (
    _check_permiso,
    logger,
    GeocodificarIndividualResponse,
    GeocodificarRequest,
    GeocodificarResponse,
    ReEnriquecerRequest,
)

_logger = logging.getLogger(__name__)

router = APIRouter()


# ── Re-enrichment manual ────────────────────────────────────────


@router.post(
    "/etiquetas-envio/re-enriquecer",
    summary="Re-enriquece etiquetas desde ml_previews con fallback HTTP",
)
async def re_enriquecer_etiquetas(
    body: ReEnriquecerRequest,
    db: Session = Depends(get_db),
    current_user: Usuario = Depends(get_current_user),
) -> dict:
    """
    Re-enriquece etiquetas en dos fases:
    1. Batch rápido: lee ml_previews directo (1 query para todos)
    2. Fallback HTTP: los que no están en ml_previews los busca
       uno por uno vía el proxy ml-webhook (~200ms c/u)

    Modos de uso:
    - Por fecha: {fecha_desde, fecha_hasta} → re-enriquece todas en ese rango
    - Por IDs:   {shipping_ids: ["123", "456"]} → re-enriquece esas específicas
    - Sin filtro: {} → re-enriquece todo lo de hoy

    Requiere permiso envios_flex.config.
    """
    _check_permiso(db, current_user, "envios_flex.config")

    # Determinar qué etiquetas re-enriquecer
    if body.shipping_ids:
        ids = body.shipping_ids
    else:
        desde = body.fecha_desde or date.today()
        hasta = body.fecha_hasta or date.today()

        etiquetas = (
            db.query(EtiquetaEnvio.shipping_id)
            .filter(
                EtiquetaEnvio.fecha_envio >= desde,
                EtiquetaEnvio.fecha_envio <= hasta,
            )
            .all()
        )
        ids = [e.shipping_id for e in etiquetas]

    if not ids:
        return {
            "actualizadas": 0,
            "sin_preview": 0,
            "fallback_ok": 0,
            "fallback_errores": 0,
            "total": 0,
            "mensaje": "No hay etiquetas para re-enriquecer",
        }

    # Fase 1: batch desde ml_previews (rápido)
    resultado_db = re_enriquecer_desde_db(ids)
    ids_sin_preview = resultado_db.get("ids_sin_preview", [])

    # Fase 2: fallback HTTP para los que no estaban en ml_previews
    fallback_ok = 0
    fallback_errores = 0
    if ids_sin_preview:
        resultado_http = await re_enriquecer_por_http(ids_sin_preview)
        fallback_ok = resultado_http["actualizadas"]
        fallback_errores = resultado_http["errores"]

    total_actualizadas = resultado_db["actualizadas"] + fallback_ok
    return {
        "actualizadas": total_actualizadas,
        "sin_preview": resultado_db["sin_preview"],
        "fallback_ok": fallback_ok,
        "fallback_errores": fallback_errores,
        "total": len(ids),
        "mensaje": (
            f"Re-enriquecidas {total_actualizadas} de {len(ids)} etiquetas "
            f"({resultado_db['actualizadas']} por DB, {fallback_ok} por HTTP, "
            f"{fallback_errores} errores)"
        ),
    }


# ── Impresión de etiquetas ZPL ──────────────────────────────────

# Errores de ML traducidos al español
_ML_LABEL_ERRORS: dict = {
    "NOT_PRINTABLE_STATUS": "El envío no está listo para imprimir (ya fue despachado, entregado o cancelado)",
    "invalid_shipment_ff_public": "Los envíos Fulfillment no permiten imprimir etiquetas desde acá",
    "invalid_shipment_mode": "Este envío no es de tipo ME2 (MercadoEnvíos 2)",
    "invalid_shipment_caller": "Usuario no autorizado para este envío",
}


@router.get(
    "/etiquetas-envio/{shipping_id}/etiqueta",
    summary="Obtiene la etiqueta ZPL de un envío desde ML",
)
async def obtener_etiqueta_zpl(
    shipping_id: str,
    current_user: Usuario = Depends(get_current_user),
    db: Session = Depends(get_db),
) -> dict:
    """
    Obtiene la etiqueta ZPL de un envío desde MercadoLibre vía ml-webhook proxy.

    Devuelve {ok: true, zpl: "^XA..."} si la etiqueta está disponible,
    o {ok: false, error: "...", code: "..."} con error descriptivo en español.

    Solo se puede imprimir si el envío está en ready_to_ship / ready_to_print o printed.
    Requiere permiso envios_flex.ver.
    """
    _check_permiso(db, current_user, "envios_flex.ver")

    # Verificar que la etiqueta existe en nuestro sistema
    etiqueta = db.query(EtiquetaEnvio).filter(EtiquetaEnvio.shipping_id == shipping_id).first()
    if not etiqueta:
        raise HTTPException(status_code=404, detail="Etiqueta no encontrada")

    resultado = await fetch_shipment_label_zpl(shipping_id)

    if not resultado["ok"]:
        # Traducir error de ML al español
        code = resultado.get("code", "")
        error_es = _ML_LABEL_ERRORS.get(code, resultado.get("error", "Error desconocido"))
        return {"ok": False, "error": error_es, "code": code}

    return resultado


# ── Impresión de etiquetas ZPL para envíos manuales ─────────────────


@router.get(
    "/etiquetas-envio/{shipping_id}/etiqueta-manual",
    summary="Genera etiqueta ZPL local para un envío manual",
)
def generar_etiqueta_manual_zpl(
    shipping_id: str,
    num_bultos: int = Query(1, ge=1),
    tipo_envio_manual: Optional[str] = Query(None),
    tipo_domicilio_manual: Optional[str] = Query(None),
    current_user: Usuario = Depends(get_current_user),
    db: Session = Depends(get_db),
) -> Response:
    """
    Genera etiquetas ZPL a partir del template local (etiqueta.zpl)
    para envíos manuales (es_manual=True).

    Usa los datos del envío manual (destinatario, dirección, CP, ciudad,
    observaciones). Si el envío tiene soh_id y bra_id, obtiene los items
    del pedido ERP para incluir SKUs y cantidad.

    Parámetros:
    - shipping_id: ID del envío manual (ej: MAN_20260123_001)
    - num_bultos: Número de bultos (genera una etiqueta por bulto, 1-10)
    - tipo_envio_manual: Override del tipo de envío (ej: "Domicilio")
    - tipo_domicilio_manual: Override del tipo de domicilio (Particular/Comercial/Sucursal)
    """
    _check_permiso(db, current_user, "envios_flex.ver")

    etiqueta = db.query(EtiquetaEnvio).filter(EtiquetaEnvio.shipping_id == shipping_id).first()
    if not etiqueta:
        raise HTTPException(status_code=404, detail="Etiqueta no encontrada")

    if not etiqueta.es_manual:
        raise HTTPException(
            status_code=400,
            detail="Este envío no es manual. Usá el endpoint de etiquetas ML.",
        )

    # ── Obtener items del pedido ERP (si hay soh_id + bra_id) ────────
    cantidad_total = 0
    skus_concatenados = "N/A"
    id_pedido = "N/A"
    orden_tn = "N/A"

    if etiqueta.manual_soh_id and etiqueta.manual_bra_id:
        id_pedido = str(etiqueta.manual_soh_id)

        items_query = (
            db.query(
                SaleOrderDetail.item_id,
                SaleOrderDetail.sod_qty,
                TBItem.item_code,
            )
            .outerjoin(
                TBItem,
                and_(
                    SaleOrderDetail.item_id == TBItem.item_id,
                    SaleOrderDetail.comp_id == TBItem.comp_id,
                ),
            )
            .filter(
                and_(
                    SaleOrderDetail.soh_id == etiqueta.manual_soh_id,
                    SaleOrderDetail.bra_id == etiqueta.manual_bra_id,
                    func.coalesce(
                        SaleOrderDetail.item_id,
                        SaleOrderDetail.sod_item_id_origin,
                    ).notin_([2953, 2954]),
                )
            )
            .all()
        )

        cantidad_total = sum(float(i.sod_qty) if i.sod_qty else 0 for i in items_query)
        skus_list = [i.item_code for i in items_query if i.item_code]
        skus_concatenados = " - ".join(skus_list) if skus_list else "N/A"

    # ── Datos de dirección del envío manual ──────────────────────────
    destinatario = etiqueta.manual_receiver_name or "N/A"
    calle = etiqueta.manual_street_name or ""
    numero = etiqueta.manual_street_number or ""
    direccion = f"{calle} {numero}".strip() or "N/A"
    codigo_postal = etiqueta.manual_zip_code or "N/A"
    ciudad = etiqueta.manual_city_name or "N/A"
    observaciones = etiqueta.manual_comment or "N/A"
    # Teléfono: manual_phone tiene prioridad, fallback a TBCustomer
    telefono = etiqueta.manual_phone or None

    if not telefono and etiqueta.manual_cust_id:
        from app.models.tb_customer import TBCustomer

        cliente = (
            db.query(TBCustomer.cust_phone1, TBCustomer.cust_cellphone)
            .filter(TBCustomer.cust_id == etiqueta.manual_cust_id)
            .first()
        )
        if cliente:
            telefono = cliente.cust_cellphone or cliente.cust_phone1 or None

    telefono = telefono or "N/A"

    # ── Tipo de envío y domicilio ────────────────────────────────────
    tipo_envio = tipo_envio_manual or "Domicilio"
    tipo_domicilio = tipo_domicilio_manual or "Particular"

    # ── Leer template ZPL ────────────────────────────────────────────
    template_path = FilePath(__file__).parent.parent.parent.parent / "templates" / "etiqueta.zpl"

    try:
        with open(template_path, "r", encoding="utf-8") as f:
            zpl_template = f.read()
    except FileNotFoundError:
        _logger.error(f"Template ZPL no encontrado en: {template_path}")
        raise HTTPException(status_code=500, detail="Template de etiqueta no encontrado")

    # ── Contexto para template ───────────────────────────────────────
    bra_id = etiqueta.manual_bra_id or 0
    soh_id = etiqueta.manual_soh_id or 0

    context = {
        "CANTIDAD_ITEMS_PEDIDO": str(int(cantidad_total)) if cantidad_total else "0",
        "SKUS_CONCATENADOS": skus_concatenados[:50],
        "ID_PEDIDO": id_pedido,
        "ORDEN_TN": orden_tn,
        "TIPO_ENVIO_ETIQUETA": tipo_envio,
        "NOMBRE_DESTINATARIO": destinatario,
        "TELEFONO_DESTINATARIO": telefono,
        "DIRECCION_CALLE": direccion,
        "OBSERVACIONES": observaciones,
        "CODIGO_POSTAL": codigo_postal,
        "BARRIO": ciudad,
        "TIPO_DOMICILIO": tipo_domicilio,
        "TOTAL_BULTOS": str(num_bultos),
    }

    # ── Generar etiquetas (una por bulto) ────────────────────────────
    zpl_labels = []
    for i in range(1, num_bultos + 1):
        label_context = context.copy()
        label_context["BULTO_ACTUAL"] = str(i)
        label_context["CODIGO_ENVIO"] = f"{bra_id}-{soh_id}-{i}"

        # QR data: JSON para pistoleado
        qr_obj = {
            "id": shipping_id,
            "bulto": i,
            "total_bultos": num_bultos,
        }
        if soh_id:
            qr_obj["soh_id"] = soh_id
        label_context["QR_DATA"] = json.dumps(qr_obj, separators=(",", ":"))

        rendered_zpl = zpl_template
        for key, value in label_context.items():
            rendered_zpl = rendered_zpl.replace(f"{{{{{key}}}}}", str(value))

        zpl_labels.append(rendered_zpl)

    # ── Remito de transporte (etiqueta adicional al final) ─────────
    if etiqueta.transporte_id:
        transporte = db.query(Transporte).filter(Transporte.id == etiqueta.transporte_id).first()
        if transporte:
            # Obtener nombre de logística si tiene
            logistica_nombre = "N/A"
            if etiqueta.logistica_id:
                logistica = db.query(Logistica).filter(Logistica.id == etiqueta.logistica_id).first()
                if logistica:
                    logistica_nombre = logistica.nombre

            remito_template_path = (
                FilePath(__file__).parent.parent.parent.parent / "templates" / "remito_transporte.zpl"
            )
            try:
                with open(remito_template_path, "r", encoding="utf-8") as f:
                    remito_template = f.read()

                remito_context = {
                    "FECHA_ENVIO": etiqueta.fecha_envio or "N/A",
                    "SHIPPING_ID": shipping_id,
                    "TRANSPORTE_NOMBRE": transporte.nombre or "N/A",
                    "TRANSPORTE_DIRECCION": transporte.direccion or "N/A",
                    "TRANSPORTE_CP": transporte.cp or "N/A",
                    "TRANSPORTE_LOCALIDAD": transporte.localidad or "N/A",
                    "TRANSPORTE_TELEFONO": transporte.telefono or "N/A",
                    "TRANSPORTE_HORARIO": transporte.horario or "N/A",
                    "NOMBRE_DESTINATARIO": destinatario,
                    "DIRECCION_CLIENTE": direccion,
                    "CP_CLIENTE": codigo_postal,
                    "CIUDAD_CLIENTE": ciudad,
                    "TELEFONO_DESTINATARIO": telefono,
                    "ID_PEDIDO": id_pedido,
                    "CANTIDAD_ITEMS": str(int(cantidad_total)) if cantidad_total else "0",
                    "SKUS_CONCATENADOS": skus_concatenados[:50],
                    "OBSERVACIONES": observaciones,
                    "TOTAL_BULTOS": str(num_bultos),
                    "BULTOS_PLURAL": "S" if num_bultos != 1 else "",
                    "LOGISTICA_NOMBRE": logistica_nombre,
                }

                rendered_remito = remito_template
                for key, value in remito_context.items():
                    rendered_remito = rendered_remito.replace(f"{{{{{key}}}}}", str(value))

                zpl_labels.append(rendered_remito)
                _logger.info(f"Remito de transporte '{transporte.nombre}' agregado para envío {shipping_id}")
            except FileNotFoundError:
                _logger.warning(f"Template remito_transporte.zpl no encontrado, se omite remito para {shipping_id}")

    full_zpl = "\n".join(zpl_labels)

    _logger.info(f"Generadas {num_bultos} etiquetas ZPL para envío manual {shipping_id}")

    return Response(
        content=full_zpl,
        media_type="text/plain",
        headers={"Content-Disposition": f"attachment; filename=etiqueta_manual_{shipping_id}.txt"},
    )


# ── Geocodificación masiva ───────────────────────────────────────────


@router.post(
    "/etiquetas-envio/geocodificar",
    response_model=GeocodificarResponse,
    summary="Geocodificar etiquetas (o re-geocodificar con coords de transporte)",
)
async def geocodificar_etiquetas(
    body: GeocodificarRequest,
    db: Session = Depends(get_db),
    current_user: Usuario = Depends(get_current_user),
) -> GeocodificarResponse:
    """
    Geocodifica etiquetas que no tienen lat/lng, o actualiza las que tienen
    transporte asignado para que apunten a la dirección del transporte.

    Para cada etiqueta:
      1. Si tiene transporte → SIEMPRE usar coords del transporte (aunque ya
         tenga lat/lng propias). Esto corrige envíos que apuntan a la
         dirección del cliente cuando deberían apuntar al transporte.
      2. Si NO tiene transporte y ya tiene coords → skip (ya_tenian).
      3. Geocodificar dirección del cliente (manual, enriquecida, o ML).
    """
    _check_permiso(db, current_user, "envios_flex.asignar_logistica")

    if len(body.shipping_ids) > 200:
        raise HTTPException(status_code=400, detail="Máximo 200 etiquetas por request")

    etiquetas = db.query(EtiquetaEnvio).filter(EtiquetaEnvio.shipping_id.in_(body.shipping_ids)).all()

    geocodificados = 0
    ya_tenian = 0
    sin_resultado = 0
    errores = 0

    for etiqueta in etiquetas:
        try:
            lat, lng = None, None

            # ── Con transporte: SIEMPRE usar coords del transporte ──
            if etiqueta.transporte_id:
                transporte = db.query(Transporte).filter(Transporte.id == etiqueta.transporte_id).first()
                if transporte:
                    if transporte.latitud and transporte.longitud:
                        lat, lng = transporte.latitud, transporte.longitud
                    elif transporte.direccion:
                        ciudad_transp = transporte.localidad or "Buenos Aires"
                        coords = await geocode_address(transporte.direccion, ciudad=ciudad_transp, db=db)
                        if coords:
                            lat, lng = coords
                            transporte.latitud = lat
                            transporte.longitud = lng

                if lat is not None and lng is not None:
                    # Actualizar aunque ya tuviera coords (pueden ser del cliente)
                    if etiqueta.latitud == lat and etiqueta.longitud == lng:
                        ya_tenian += 1
                    else:
                        etiqueta.latitud = lat
                        etiqueta.longitud = lng
                        geocodificados += 1
                        logger.info(
                            "Geocoding (transporte) %s → (%.6f, %.6f)",
                            etiqueta.shipping_id,
                            lat,
                            lng,
                        )
                    continue

                # Transporte sin coords ni dirección → caer al fallback del cliente
                # (no hacemos continue, dejamos que siga abajo)

            # ── Sin transporte: skip si ya tiene coordenadas ──
            if etiqueta.latitud and etiqueta.longitud:
                ya_tenian += 1
                continue

            # ── Fallback: dirección del cliente (manual o enriquecida) ──
            direccion = None
            ciudad = "Buenos Aires"
            zip_code = None

            if etiqueta.es_manual and etiqueta.manual_street_name:
                direccion = f"{etiqueta.manual_street_name} {etiqueta.manual_street_number or ''}".strip()
                ciudad = etiqueta.manual_city_name or "Buenos Aires"
                zip_code = etiqueta.manual_zip_code
            elif etiqueta.direccion_completa:
                direccion = etiqueta.direccion_completa
            else:
                # Buscar en ML shipping como último recurso
                ml_ship = (
                    db.query(MercadoLibreOrderShipping)
                    .filter(MercadoLibreOrderShipping.mlshippingid == etiqueta.shipping_id)
                    .first()
                )
                if ml_ship and ml_ship.mlstreet_name:
                    direccion = f"{ml_ship.mlstreet_name} {ml_ship.mlstreet_number or ''}".strip()
                    ciudad = ml_ship.mlcity_name or "Buenos Aires"
                    zip_code = ml_ship.mlzip_code

            if direccion:
                coords = await geocode_address(direccion, ciudad=ciudad, zip_code=zip_code, db=db)
                if coords:
                    lat, lng = coords

            if lat is not None and lng is not None:
                etiqueta.latitud = lat
                etiqueta.longitud = lng
                geocodificados += 1
                logger.info("Geocoding OK %s → (%.6f, %.6f)", etiqueta.shipping_id, lat, lng)
            else:
                sin_resultado += 1
                logger.warning("Geocoding sin resultado para %s", etiqueta.shipping_id)

        except Exception:
            logger.exception("Error geocodificando %s", etiqueta.shipping_id)
            errores += 1

    db.commit()
    if geocodificados > 0:
        sse_publish_bg("etiquetas:changed", {"hint": "reload"})

    return GeocodificarResponse(
        total=len(etiquetas),
        geocodificados=geocodificados,
        ya_tenian=ya_tenian,
        sin_resultado=sin_resultado,
        errores=errores,
    )


# ── Geocodificación / Re-geocodificación individual ──────────────────


@router.post(
    "/etiquetas-envio/{shipping_id}/geocodificar",
    response_model=GeocodificarIndividualResponse,
    summary="Re-geocodificar una etiqueta individual (fuerza re-cálculo aunque ya tenga coords)",
)
async def geocodificar_individual(
    shipping_id: str,
    db: Session = Depends(get_db),
    current_user: Usuario = Depends(get_current_user),
) -> GeocodificarIndividualResponse:
    """
    Re-geocodifica una etiqueta individual FORZANDO el re-cálculo.
    A diferencia del masivo, esto SIEMPRE re-geocodifica aunque ya tenga
    coordenadas, permitiendo corregir errores de geocodificación.

    No tiene límite de selección — es para corrección puntual.
    """
    _check_permiso(db, current_user, "envios_flex.asignar_logistica")

    etiqueta = db.query(EtiquetaEnvio).filter(EtiquetaEnvio.shipping_id == shipping_id).first()
    if not etiqueta:
        raise HTTPException(status_code=404, detail="Etiqueta no encontrada")

    # ── Determinar dirección a geocodificar ──
    direccion = None
    ciudad = "Buenos Aires"
    zip_code = None

    # Prioridad 1: transporte asignado
    if etiqueta.transporte_id:
        transporte = db.query(Transporte).filter(Transporte.id == etiqueta.transporte_id).first()
        if transporte:
            if transporte.latitud and transporte.longitud:
                # Transporte ya tiene coords → usar directo
                etiqueta.latitud = transporte.latitud
                etiqueta.longitud = transporte.longitud
                db.commit()
                sse_publish_bg("etiquetas:changed", {"hint": "reload"})
                return GeocodificarIndividualResponse(
                    shipping_id=shipping_id,
                    latitud=float(transporte.latitud),
                    longitud=float(transporte.longitud),
                    direccion_usada=transporte.direccion,
                    ok=True,
                    mensaje="Coords tomadas del transporte asignado",
                )
            if transporte.direccion:
                direccion = transporte.direccion
                ciudad = transporte.localidad or "Buenos Aires"
                zip_code = transporte.cp

    # Prioridad 2: dirección manual
    if not direccion and etiqueta.es_manual and etiqueta.manual_street_name:
        direccion = f"{etiqueta.manual_street_name} {etiqueta.manual_street_number or ''}".strip()
        ciudad = etiqueta.manual_city_name or "Buenos Aires"
        zip_code = etiqueta.manual_zip_code

    # Prioridad 3: dirección enriquecida
    if not direccion and etiqueta.direccion_completa:
        direccion = etiqueta.direccion_completa
        # Intentar extraer CP del envío
        zip_code = zip_code or etiqueta.manual_zip_code

    # Prioridad 4: ML shipping data
    if not direccion:
        ml_ship = (
            db.query(MercadoLibreOrderShipping).filter(MercadoLibreOrderShipping.mlshippingid == shipping_id).first()
        )
        if ml_ship and ml_ship.mlstreet_name:
            direccion = f"{ml_ship.mlstreet_name} {ml_ship.mlstreet_number or ''}".strip()
            ciudad = ml_ship.mlcity_name or "Buenos Aires"
            zip_code = ml_ship.mlzip_code

    if not direccion:
        return GeocodificarIndividualResponse(
            shipping_id=shipping_id,
            ok=False,
            mensaje="Sin dirección válida para geocodificar",
        )

    # ── Geocodificar (bypass cache para forzar re-cálculo) ──
    coords = await geocode_address(
        direccion,
        ciudad=ciudad,
        zip_code=zip_code,
        db=db,
        usar_cache=False,
    )

    if not coords:
        # Limpiar coords erróneas si las tenía
        if etiqueta.latitud or etiqueta.longitud:
            etiqueta.latitud = None
            etiqueta.longitud = None
            db.commit()
            sse_publish_bg("etiquetas:changed", {"hint": "reload"})
        return GeocodificarIndividualResponse(
            shipping_id=shipping_id,
            direccion_usada=f"{direccion}, {ciudad}",
            ok=False,
            mensaje="No se encontró una ubicación confiable para esta dirección",
        )

    lat, lng = coords
    etiqueta.latitud = lat
    etiqueta.longitud = lng
    db.commit()
    sse_publish_bg("etiquetas:changed", {"hint": "reload"})

    logger.info(
        "Re-geocoding individual OK %s → (%.6f, %.6f) [%s]",
        shipping_id,
        lat,
        lng,
        direccion[:50],
    )

    return GeocodificarIndividualResponse(
        shipping_id=shipping_id,
        latitud=lat,
        longitud=lng,
        direccion_usada=f"{direccion}, {ciudad}",
        ok=True,
        mensaje="Geocodificación exitosa",
    )
