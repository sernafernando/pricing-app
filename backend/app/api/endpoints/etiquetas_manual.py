"""
Endpoints de envíos manuales (sin MercadoLibre).

Incluye:
- GET /etiquetas-envio/lookup-pedido (buscar pedido ERP)
- POST /etiquetas-envio/desde-pedido (crear desde Pedidos Pendientes)
- POST /etiquetas-envio/manual-envio (crear envío manual)
- PUT /etiquetas-envio/manual-envio/{shipping_id} (editar envío manual)
- PUT /etiquetas-envio/{shipping_id}/estado-ml (cambiar estado ML de manual)
"""

import logging
from datetime import datetime, UTC
from typing import Optional

from fastapi import APIRouter, BackgroundTasks, Depends, HTTPException, Query
from sqlalchemy import func
from sqlalchemy.orm import Session

from app.core.database import get_db
from app.core.sse import sse_publish_bg
from app.api.deps import get_current_user
from app.models.usuario import Usuario
from app.models.etiqueta_envio import EtiquetaEnvio
from app.models.logistica import Logistica
from app.models.transporte import Transporte
from app.models.codigo_postal_cordon import CodigoPostalCordon
from app.models.sale_order_header import SaleOrderHeader
from app.models.operador import Operador
from app.models.operador_actividad import OperadorActividad
from app.models.rma_caso_item import RmaCasoItem
from app.models.rma_seguimiento_opcion import RmaSeguimientoOpcion
from app.models.rma_caso_historial import RmaCasoHistorial
from app.services.permisos_service import verificar_permiso

from app.api.endpoints.etiquetas_shared import (
    _check_permiso,
    _geocode_envio_manual,
    CrearDesdePedidoRequest,
    CrearEnvioManualRequest,
    CrearEnvioManualResponse,
)

logger = logging.getLogger(__name__)

router = APIRouter()


@router.get(
    "/etiquetas-envio/lookup-pedido",
    response_model=dict,
    summary="Buscar pedido ERP por soh_id + bra_id → devuelve cust_id",
)
def lookup_pedido(
    soh_id: int = Query(..., description="N° pedido ERP"),
    bra_id: int = Query(..., description="Sucursal"),
    db: Session = Depends(get_db),
    current_user: Usuario = Depends(get_current_user),
) -> dict:
    """
    Busca un pedido en SaleOrderHeader por comp_id=1 + bra_id + soh_id
    y devuelve el cust_id asociado para autocompletar la dirección
    del cliente en el modal de envío manual.

    Acepta envios_flex.subir_etiquetas (tab Envíos Flex) O
    pedidos.crear_envio_flex (tab Pedidos Pendientes).
    """
    if not verificar_permiso(db, current_user, "envios_flex.subir_etiquetas") and not verificar_permiso(
        db, current_user, "pedidos.crear_envio_flex"
    ):
        raise HTTPException(
            status_code=403,
            detail="No tenés permiso: envios_flex.subir_etiquetas o pedidos.crear_envio_flex",
        )

    from app.models.tb_customer import TBCustomer

    soh = (
        db.query(
            SaleOrderHeader.cust_id,
            SaleOrderHeader.soh_id,
        )
        .filter(
            SaleOrderHeader.comp_id == 1,
            SaleOrderHeader.bra_id == bra_id,
            SaleOrderHeader.soh_id == soh_id,
        )
        .first()
    )
    if not soh:
        raise HTTPException(
            404,
            f"Pedido {soh_id} no encontrado en sucursal {bra_id}",
        )

    # Buscar datos del cliente para autocompletar
    cliente = (
        db.query(
            TBCustomer.cust_id,
            TBCustomer.cust_name,
            TBCustomer.cust_address,
            TBCustomer.cust_city,
            TBCustomer.cust_zip,
            TBCustomer.cust_phone1,
            TBCustomer.cust_cellphone,
        )
        .filter(
            TBCustomer.comp_id == 1,
            TBCustomer.cust_id == soh.cust_id,
        )
        .first()
    )

    return {
        "soh_id": soh_id,
        "bra_id": bra_id,
        "cust_id": soh.cust_id,
        "cust_name": cliente.cust_name if cliente else None,
        "cust_address": cliente.cust_address if cliente else None,
        "cust_city": cliente.cust_city if cliente else None,
        "cust_zip": cliente.cust_zip if cliente else None,
        "cust_phone1": cliente.cust_phone1 if cliente else None,
        "cust_cellphone": cliente.cust_cellphone if cliente else None,
    }


@router.post(
    "/etiquetas-envio/desde-pedido",
    response_model=CrearEnvioManualResponse,
    summary="Crear envío flex desde Pedidos Pendientes",
)
def crear_envio_desde_pedido(
    payload: CrearDesdePedidoRequest,
    background_tasks: BackgroundTasks,
    db: Session = Depends(get_db),
    current_user: Usuario = Depends(get_current_user),
) -> CrearEnvioManualResponse:
    """
    Crea un envío flex manual desde la tab Pedidos Pendientes.

    Similar a crear_envio_manual pero NO requiere operador (lo crea otro sector).
    Guarda el usuario del sistema que lo creó en creado_por_usuario_id para
    trazabilidad visual en la grilla de Envíos Flex.
    """
    _check_permiso(db, current_user, "pedidos.crear_envio_flex")

    # Resolver cust_id desde SaleOrderHeader (solo si se pasó soh_id + bra_id)
    resolved_cust_id: Optional[int] = payload.cust_id
    if payload.soh_id and payload.bra_id:
        soh = (
            db.query(SaleOrderHeader.cust_id)
            .filter(
                SaleOrderHeader.comp_id == 1,
                SaleOrderHeader.bra_id == payload.bra_id,
                SaleOrderHeader.soh_id == payload.soh_id,
            )
            .first()
        )
        if not soh:
            raise HTTPException(
                404,
                f"Pedido {payload.soh_id} no encontrado en sucursal {payload.bra_id}",
            )
        resolved_cust_id = soh.cust_id

    # Generar shipping_id único: MAN_{timestamp}_{seq}
    ahora = datetime.now(UTC)
    ts = ahora.strftime("%Y%m%d%H%M%S")
    prefix = f"MAN_{ts}_"
    count = (
        db.query(func.count()).select_from(EtiquetaEnvio).filter(EtiquetaEnvio.shipping_id.like(f"{prefix}%")).scalar()
        or 0
    )
    shipping_id = f"{prefix}{count + 1}"

    # Validar transporte si se envió
    transporte = None
    if payload.transporte_id is not None:
        transporte = (
            db.query(Transporte).filter(Transporte.id == payload.transporte_id, Transporte.activa.is_(True)).first()
        )
        if not transporte:
            raise HTTPException(404, "Transporte no encontrado o inactivo")

    etiqueta = EtiquetaEnvio(
        shipping_id=shipping_id,
        fecha_envio=payload.fecha_envio,
        es_manual=True,
        manual_receiver_name=payload.receiver_name,
        manual_street_name=payload.street_name,
        manual_street_number=payload.street_number,
        manual_zip_code=payload.zip_code,
        manual_city_name=payload.city_name,
        manual_status=payload.status or "ready_to_ship",
        manual_cust_id=resolved_cust_id,
        manual_bra_id=payload.bra_id,
        manual_soh_id=payload.soh_id,
        manual_comment=payload.comment,
        manual_phone=payload.phone,
        logistica_id=payload.logistica_id,
        transporte_id=payload.transporte_id,
        nombre_archivo="desde_pedido",
        creado_por_usuario_id=current_user.id,
    )
    db.add(etiqueta)

    try:
        db.commit()
    except Exception as e:
        db.rollback()
        raise HTTPException(500, f"Error creando envío desde pedido: {str(e)}")

    # Resolver cordón: si hay transporte con CP, usar ese CP (zona de entrega
    # de la logística); sino, usar el CP del cliente.
    cp_for_cordon = payload.zip_code
    if payload.transporte_id is not None and transporte and transporte.cp:
        cp_for_cordon = transporte.cp

    cordon_val = None
    if cp_for_cordon:
        cordon_row = (
            db.query(CodigoPostalCordon.cordon).filter(CodigoPostalCordon.codigo_postal == cp_for_cordon).first()
        )
        cordon_val = cordon_row.cordon if cordon_row else None

    # Geocodificar en background (no bloquea la respuesta)
    background_tasks.add_task(
        _geocode_envio_manual,
        shipping_id=shipping_id,
        street_name=payload.street_name,
        street_number=payload.street_number,
        city_name=payload.city_name,
        transporte_id=payload.transporte_id,
        zip_code=payload.zip_code,
    )

    # SSE: notify clients that etiquetas changed
    sse_publish_bg("etiquetas:changed", {"hint": "reload"})

    soh_label = f" desde pedido GBP:{payload.soh_id}" if payload.soh_id else ""
    return CrearEnvioManualResponse(
        ok=True,
        shipping_id=shipping_id,
        cordon=cordon_val,
        mensaje=f"Envío flex creado{soh_label}",
    )


@router.post(
    "/etiquetas-envio/manual-envio",
    response_model=CrearEnvioManualResponse,
    summary="Crear envío manual (sin MercadoLibre)",
)
def crear_envio_manual(
    payload: CrearEnvioManualRequest,
    background_tasks: BackgroundTasks,
    db: Session = Depends(get_db),
    current_user: Usuario = Depends(get_current_user),
) -> CrearEnvioManualResponse:
    """
    Crea una etiqueta de envío manual para envíos fuera de MercadoLibre.

    Genera un shipping_id con formato "MAN_{timestamp}_{seq}" para no
    colisionar con los IDs de ML.  Los datos de dirección se guardan
    en los campos manual_* de la etiqueta.

    Requiere envios_flex.subir_etiquetas y operador autenticado con PIN.
    Registra la acción en operador_actividad para auditoría.
    """
    _check_permiso(db, current_user, "envios_flex.subir_etiquetas")

    # Validar operador activo
    operador = db.query(Operador).filter(Operador.id == payload.operador_id, Operador.activo.is_(True)).first()
    if not operador:
        raise HTTPException(404, "Operador no encontrado o inactivo")

    # Validar logística si se envió
    if payload.logistica_id is not None:
        logistica = db.query(Logistica).filter(Logistica.id == payload.logistica_id, Logistica.activa.is_(True)).first()
        if not logistica:
            raise HTTPException(404, "Logística no encontrada o inactiva")

    # Validar transporte si se envió
    transporte = None
    if payload.transporte_id is not None:
        transporte = (
            db.query(Transporte).filter(Transporte.id == payload.transporte_id, Transporte.activa.is_(True)).first()
        )
        if not transporte:
            raise HTTPException(404, "Transporte no encontrado o inactivo")

    # Si viene soh_id + bra_id, resolver cust_id desde SaleOrderHeader
    resolved_cust_id = payload.cust_id
    if payload.soh_id and payload.bra_id and not resolved_cust_id:
        soh = (
            db.query(SaleOrderHeader.cust_id)
            .filter(
                SaleOrderHeader.comp_id == 1,
                SaleOrderHeader.bra_id == payload.bra_id,
                SaleOrderHeader.soh_id == payload.soh_id,
            )
            .first()
        )
        if not soh:
            raise HTTPException(
                404,
                f"Pedido {payload.soh_id} no encontrado en sucursal {payload.bra_id}",
            )
        resolved_cust_id = soh.cust_id

    # Generar shipping_id único: MAN_{timestamp}_{seq}
    ahora = datetime.now(UTC)
    ts = ahora.strftime("%Y%m%d%H%M%S")

    # Secuencia: contar cuántos manuales hay con el mismo segundo
    prefix = f"MAN_{ts}_"
    count = (
        db.query(func.count()).select_from(EtiquetaEnvio).filter(EtiquetaEnvio.shipping_id.like(f"{prefix}%")).scalar()
        or 0
    )
    shipping_id = f"{prefix}{count + 1}"

    # Crear etiqueta manual
    etiqueta = EtiquetaEnvio(
        shipping_id=shipping_id,
        fecha_envio=payload.fecha_envio,
        logistica_id=payload.logistica_id,
        transporte_id=payload.transporte_id,
        es_manual=True,
        manual_receiver_name=payload.receiver_name,
        manual_street_name=payload.street_name,
        manual_street_number=payload.street_number,
        manual_zip_code=payload.zip_code,
        manual_city_name=payload.city_name,
        manual_status=payload.status,
        manual_cust_id=resolved_cust_id,
        manual_bra_id=payload.bra_id,
        manual_soh_id=payload.soh_id,
        manual_comment=payload.comment,
        manual_phone=payload.phone,
        nombre_archivo="envio_manual",
    )
    db.add(etiqueta)

    # Registrar actividad del operador
    actividad = OperadorActividad(
        operador_id=payload.operador_id,
        usuario_id=current_user.id,
        tab_key="envios-flex",
        accion="crear_envio_manual",
        detalle={
            "shipping_id": shipping_id,
            "receiver_name": payload.receiver_name,
            "street_name": payload.street_name,
            "street_number": payload.street_number,
            "zip_code": payload.zip_code,
            "city_name": payload.city_name,
            "status": payload.status,
            "cust_id": resolved_cust_id,
            "bra_id": payload.bra_id,
            "soh_id": payload.soh_id,
            "logistica_id": payload.logistica_id,
            "transporte_id": payload.transporte_id,
            "comment": payload.comment,
        },
    )
    db.add(actividad)

    try:
        db.commit()
    except Exception as e:
        db.rollback()
        raise HTTPException(500, f"Error guardando envío manual: {str(e)}")

    # Resolver cordón: si hay transporte con CP, usar ese CP; sino, CP del cliente.
    cp_for_cordon = payload.zip_code
    if payload.transporte_id is not None and transporte and transporte.cp:
        cp_for_cordon = transporte.cp

    cordon_val = None
    if cp_for_cordon:
        cordon_row = (
            db.query(CodigoPostalCordon.cordon).filter(CodigoPostalCordon.codigo_postal == cp_for_cordon).first()
        )
        cordon_val = cordon_row.cordon if cordon_row else None

    # Geocodificar en background (no bloquea la respuesta)
    background_tasks.add_task(
        _geocode_envio_manual,
        shipping_id=shipping_id,
        street_name=payload.street_name,
        street_number=payload.street_number,
        city_name=payload.city_name,
        transporte_id=payload.transporte_id,
        zip_code=payload.zip_code,
    )

    # SSE: notify clients that etiquetas changed
    sse_publish_bg("etiquetas:changed", {"hint": "reload"})

    return CrearEnvioManualResponse(
        ok=True,
        shipping_id=shipping_id,
        cordon=cordon_val,
        mensaje=f"Envío manual creado: {shipping_id}",
    )


@router.put(
    "/etiquetas-envio/manual-envio/{shipping_id}",
    response_model=dict,
    summary="Editar envío manual existente",
)
def editar_envio_manual(
    shipping_id: str,
    payload: CrearEnvioManualRequest,
    background_tasks: BackgroundTasks,
    db: Session = Depends(get_db),
    current_user: Usuario = Depends(get_current_user),
) -> dict:
    """
    Edita los datos de un envío manual existente (es_manual=True).

    Permite corregir destinatario, dirección, logística, estado, etc.
    sin tener que borrar y recrear el envío.
    Requiere envios_flex.subir_etiquetas y operador autenticado con PIN.
    """
    _check_permiso(db, current_user, "envios_flex.subir_etiquetas")

    etiqueta = db.query(EtiquetaEnvio).filter(EtiquetaEnvio.shipping_id == shipping_id).first()
    if not etiqueta:
        raise HTTPException(404, f"Etiqueta {shipping_id} no encontrada")

    if not etiqueta.es_manual:
        raise HTTPException(400, "Solo se pueden editar envíos manuales")

    # Validar operador activo
    operador = db.query(Operador).filter(Operador.id == payload.operador_id, Operador.activo.is_(True)).first()
    if not operador:
        raise HTTPException(404, "Operador no encontrado o inactivo")

    # Validar logística si se envió
    if payload.logistica_id is not None:
        logistica = db.query(Logistica).filter(Logistica.id == payload.logistica_id, Logistica.activa.is_(True)).first()
        if not logistica:
            raise HTTPException(404, "Logística no encontrada o inactiva")

    # Validar transporte si se envió
    transporte_obj = None
    if payload.transporte_id is not None:
        transporte_obj = (
            db.query(Transporte).filter(Transporte.id == payload.transporte_id, Transporte.activa.is_(True)).first()
        )
        if not transporte_obj:
            raise HTTPException(404, "Transporte no encontrado o inactivo")

    # Resolver cust_id desde pedido si corresponde
    resolved_cust_id = payload.cust_id
    if payload.soh_id and payload.bra_id and not resolved_cust_id:
        soh = (
            db.query(SaleOrderHeader.cust_id)
            .filter(
                SaleOrderHeader.comp_id == 1,
                SaleOrderHeader.bra_id == payload.bra_id,
                SaleOrderHeader.soh_id == payload.soh_id,
            )
            .first()
        )
        if not soh:
            raise HTTPException(
                404,
                f"Pedido {payload.soh_id} no encontrado en sucursal {payload.bra_id}",
            )
        resolved_cust_id = soh.cust_id

    # Detectar si la dirección cambió → necesita re-geocoding
    direccion_cambio = (
        (etiqueta.manual_street_name or "") != (payload.street_name or "")
        or (etiqueta.manual_street_number or "") != (payload.street_number or "")
        or (etiqueta.manual_city_name or "") != (payload.city_name or "")
        or (etiqueta.manual_zip_code or "") != (payload.zip_code or "")
        or (etiqueta.transporte_id or None) != (payload.transporte_id or None)
    )

    # Guardar estado anterior para auditoría
    estado_anterior = {
        "receiver_name": etiqueta.manual_receiver_name,
        "street_name": etiqueta.manual_street_name,
        "street_number": etiqueta.manual_street_number,
        "zip_code": etiqueta.manual_zip_code,
        "city_name": etiqueta.manual_city_name,
        "status": etiqueta.manual_status,
        "logistica_id": etiqueta.logistica_id,
        "transporte_id": etiqueta.transporte_id,
        "cust_id": etiqueta.manual_cust_id,
        "bra_id": etiqueta.manual_bra_id,
        "soh_id": etiqueta.manual_soh_id,
        "comment": etiqueta.manual_comment,
        "phone": etiqueta.manual_phone,
    }

    # Si la dirección cambió, limpiar coords viejas para forzar re-geocoding
    if direccion_cambio:
        etiqueta.latitud = None
        etiqueta.longitud = None

    # Actualizar campos
    etiqueta.fecha_envio = payload.fecha_envio
    etiqueta.manual_receiver_name = payload.receiver_name
    etiqueta.manual_street_name = payload.street_name
    etiqueta.manual_street_number = payload.street_number
    etiqueta.manual_zip_code = payload.zip_code
    etiqueta.manual_city_name = payload.city_name
    etiqueta.manual_status = payload.status
    etiqueta.manual_cust_id = resolved_cust_id
    etiqueta.manual_bra_id = payload.bra_id
    etiqueta.manual_soh_id = payload.soh_id
    etiqueta.manual_comment = payload.comment
    etiqueta.manual_phone = payload.phone
    etiqueta.logistica_id = payload.logistica_id
    etiqueta.transporte_id = payload.transporte_id

    # Registrar actividad
    actividad = OperadorActividad(
        operador_id=payload.operador_id,
        usuario_id=current_user.id,
        tab_key="envios-flex",
        accion="editar_envio_manual",
        detalle={
            "shipping_id": shipping_id,
            "anterior": estado_anterior,
            "nuevo": {
                "receiver_name": payload.receiver_name,
                "street_name": payload.street_name,
                "street_number": payload.street_number,
                "zip_code": payload.zip_code,
                "city_name": payload.city_name,
                "status": payload.status,
                "logistica_id": payload.logistica_id,
                "transporte_id": payload.transporte_id,
                "cust_id": resolved_cust_id,
                "bra_id": payload.bra_id,
                "soh_id": payload.soh_id,
                "comment": payload.comment,
                "phone": payload.phone,
            },
        },
    )
    db.add(actividad)

    try:
        db.commit()
    except Exception as e:
        db.rollback()
        raise HTTPException(500, f"Error guardando cambios: {str(e)}")

    # Si la dirección cambió, re-geocodificar en background
    if direccion_cambio:
        background_tasks.add_task(
            _geocode_envio_manual,
            shipping_id=shipping_id,
            street_name=payload.street_name,
            street_number=payload.street_number,
            city_name=payload.city_name,
            transporte_id=payload.transporte_id,
            zip_code=payload.zip_code,
        )
        logger.info(
            "Dirección cambió para %s → re-geocodificando en background",
            shipping_id,
        )

    # Resolver cordón: si hay transporte con CP, usar ese CP; sino, CP del cliente.
    cp_for_cordon = payload.zip_code
    if payload.transporte_id is not None and transporte_obj and transporte_obj.cp:
        cp_for_cordon = transporte_obj.cp

    cordon_val = None
    if cp_for_cordon:
        cordon_row = (
            db.query(CodigoPostalCordon.cordon).filter(CodigoPostalCordon.codigo_postal == cp_for_cordon).first()
        )
        cordon_val = cordon_row.cordon if cordon_row else None

    # SSE: notify clients that etiquetas changed
    sse_publish_bg("etiquetas:changed", {"hint": "reload"})

    return {
        "ok": True,
        "shipping_id": shipping_id,
        "cordon": cordon_val,
        "mensaje": f"Envío {shipping_id} actualizado",
    }


# ── RMA estado_proveedor sync ──────────────────────────────────

# Maps manual_status values to estado_proveedor option names.
# Universal shipment status pattern: loaded → in-transit → delivered.
_ML_STATUS_TO_ESTADO_PROVEEDOR: dict[str, str] = {
    "ready_to_ship": "Envío cargado",
    "shipped": "Enviado a proveedor",
    "delivered": "Entregado a proveedor",
}


def _sync_rma_estado_proveedor(
    db: Session,
    shipping_id: str,
    new_ml_status: str,
    usuario_id: int,
) -> int:
    """Propagate manual_status change to estado_proveedor of linked RMA items.

    When depósito changes the shipment status in TabEnviosFlex, this function
    maps the new ML status to the corresponding estado_proveedor option and
    updates all RMA items linked to the shipping_id.

    Returns the number of items updated.
    """
    target_valor = _ML_STATUS_TO_ESTADO_PROVEEDOR.get(new_ml_status)
    if not target_valor:
        return 0

    opcion = (
        db.query(RmaSeguimientoOpcion)
        .filter(
            RmaSeguimientoOpcion.categoria == "estado_proveedor",
            RmaSeguimientoOpcion.valor == target_valor,
            RmaSeguimientoOpcion.activo == True,  # noqa: E712
        )
        .first()
    )
    if not opcion:
        logger.warning("RMA estado_proveedor option '%s' not found", target_valor)
        return 0

    # Find linked RMA items (proveedor shipments use shipping_id,
    # cliente shipments use shipping_cliente_id)
    if shipping_id.startswith("RMA_"):
        rma_items = db.query(RmaCasoItem).filter(RmaCasoItem.shipping_id == shipping_id).all()
    else:
        # RMACLI_ shipments don't affect estado_proveedor
        return 0

    updated = 0
    for item in rma_items:
        if item.estado_proveedor_id == opcion.id:
            continue  # already at target state

        old_estado = item.estado_proveedor_id
        item.estado_proveedor_id = opcion.id
        updated += 1

        # Audit trail
        db.add(
            RmaCasoHistorial(
                caso_id=item.caso_id,
                caso_item_id=item.id,
                campo="estado_proveedor_id",
                valor_anterior=str(old_estado) if old_estado else None,
                valor_nuevo=str(opcion.id),
                usuario_id=usuario_id,
            )
        )

    if updated:
        logger.info(
            "RMA sync: %d items updated to '%s' for shipping %s",
            updated,
            target_valor,
            shipping_id,
        )

    return updated


@router.put(
    "/etiquetas-envio/{shipping_id}/estado-ml",
    response_model=dict,
    summary="Cambiar estado ML de un envío manual",
)
def cambiar_estado_ml(
    shipping_id: str,
    status: str = Query(
        ...,
        description="Nuevo estado: ready_to_ship, shipped, delivered",
        pattern="^(ready_to_ship|shipped|delivered)$",
    ),
    operador_id: int = Query(..., description="Operador autenticado con PIN"),
    db: Session = Depends(get_db),
    current_user: Usuario = Depends(get_current_user),
) -> dict:
    """
    Cambia el estado ML (manual_status) de un envío manual.

    Solo aplica a etiquetas con es_manual=True.
    Registra la acción en operador_actividad.
    Requiere permiso envios_flex.cambiar_estado_manual.
    """
    _check_permiso(db, current_user, "envios_flex.cambiar_estado_manual")

    etiqueta = db.query(EtiquetaEnvio).filter(EtiquetaEnvio.shipping_id == shipping_id).first()
    if not etiqueta:
        raise HTTPException(404, f"Etiqueta {shipping_id} no encontrada")

    if not etiqueta.es_manual:
        raise HTTPException(
            400,
            "Solo se puede cambiar el estado ML de envíos manuales",
        )

    # Validar operador activo
    operador = db.query(Operador).filter(Operador.id == operador_id, Operador.activo.is_(True)).first()
    if not operador:
        raise HTTPException(404, "Operador no encontrado o inactivo")

    estado_anterior = etiqueta.manual_status
    etiqueta.manual_status = status

    # Registrar actividad
    actividad = OperadorActividad(
        operador_id=operador_id,
        usuario_id=current_user.id,
        tab_key="envios-flex",
        accion="cambiar_estado_manual",
        detalle={
            "shipping_id": shipping_id,
            "estado_anterior": estado_anterior,
            "estado_nuevo": status,
        },
    )
    db.add(actividad)

    # ── Propagate to RMA items if this is an RMA shipment ──
    rma_items_updated = 0
    if shipping_id.startswith("RMA_") or shipping_id.startswith("RMACLI_"):
        rma_items_updated = _sync_rma_estado_proveedor(db, shipping_id, status, current_user.id)

    db.commit()
    sse_publish_bg("etiquetas:changed", {"hint": "reload"})

    return {
        "ok": True,
        "shipping_id": shipping_id,
        "estado_anterior": estado_anterior,
        "estado_nuevo": status,
        "rma_items_updated": rma_items_updated,
    }
