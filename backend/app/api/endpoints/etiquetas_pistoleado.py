"""
Endpoints de pistoleado (escaneo de paquetes en depósito).

Incluye:
- POST /etiquetas-envio/pistolear (escaneo de paquete)
- GET /etiquetas-envio/pistoleado/stats (estadísticas de pistoleado)
- DELETE /etiquetas-envio/pistolear/{shipping_id} (deshacer pistoleado)
"""

import json
from datetime import date, datetime, UTC

from fastapi import APIRouter, Depends, HTTPException, Query
from sqlalchemy import desc, func
from sqlalchemy.orm import Session
from typing import Optional

from app.core.database import get_db
from app.core.sse import sse_publish_bg
from app.api.deps import get_current_user
from app.models.usuario import Usuario
from app.models.etiqueta_envio import EtiquetaEnvio
from app.models.logistica import Logistica
from app.models.codigo_postal_cordon import CodigoPostalCordon
from app.models.sale_order_header import SaleOrderHeader
from app.models.sale_order_status import SaleOrderStatus
from app.models.mercadolibre_order_shipping import MercadoLibreOrderShipping
from app.models.operador import Operador
from app.models.operador_actividad import OperadorActividad

from app.api.endpoints.etiquetas_shared import (
    _check_permiso,
    PistolearRequest,
    PistolearResponse,
    PistoleadoStatsResponse,
)

router = APIRouter()


@router.post(
    "/etiquetas-envio/pistolear",
    response_model=PistolearResponse,
    summary="Pistolear etiqueta (escaneo de paquete en depósito)",
    responses={
        409: {"description": "Ya pistoleada"},
        422: {"description": "Logística no coincide"},
    },
)
def pistolear_etiqueta(
    payload: PistolearRequest,
    db: Session = Depends(get_db),
    current_user: Usuario = Depends(get_current_user),
) -> PistolearResponse:
    """
    Registra el pistoleado de una etiqueta de envío.

    El operador escanea el QR de la etiqueta con pistola de barras.

    Dos modos de operación:
    - **Bulto único / ML**: si `bulto` es None → comportamiento clásico.
      Duplicado completo → 409.
    - **Multi-bulto (manuales)**: si `bulto` y `total_bultos` están presentes
      y total_bultos > 1 → tracking per-bulto en `pistoleado_bultos` (JSON array).
      Duplicado de bulto específico → 409. `pistoleado_at` se setea solo cuando
      TODOS los bultos fueron escaneados.

    Validaciones:
    1. La etiqueta debe existir en el sistema (→ 404).
    2. La logística asignada debe coincidir (→ 422).
    3. No debe haber sido pistoleada antes — por envío completo o por bulto (→ 409).

    Side effects:
    - Graba pistoleado_at, pistoleado_caja, pistoleado_operador_id.
    - En multi-bulto: actualiza pistoleado_bultos JSON array y total_bultos.
    - Registra actividad en operador_actividad.
    """
    _check_permiso(db, current_user, "envios_flex.pistoleado")

    # Validar operador activo
    operador = (
        db.query(Operador)
        .filter(
            Operador.id == payload.operador_id,
            Operador.activo.is_(True),
        )
        .first()
    )
    if not operador:
        raise HTTPException(404, "Operador no encontrado o inactivo")

    # Buscar etiqueta
    etiqueta = (
        db.query(EtiquetaEnvio)
        .filter(
            EtiquetaEnvio.shipping_id == payload.shipping_id,
        )
        .first()
    )
    if not etiqueta:
        raise HTTPException(404, f"Etiqueta {payload.shipping_id} no encontrada en el sistema")

    # Validar logística coincide — o asignar si pistoleado_asigna está activo
    logistica_pistoleando = db.query(Logistica).filter(Logistica.id == payload.logistica_id).first()
    if not logistica_pistoleando:
        raise HTTPException(404, "Logística de pistoleado no encontrada")

    fue_asignada = False
    if etiqueta.logistica_id is not None and etiqueta.logistica_id != payload.logistica_id:
        if logistica_pistoleando.pistoleado_asigna:
            # Modo asignación: reasignar la logística de la etiqueta
            etiqueta.logistica_id = payload.logistica_id
            fue_asignada = True
        else:
            # Modo estricto: rechazar si no coincide
            logistica_etiq = db.query(Logistica).filter(Logistica.id == etiqueta.logistica_id).first()
            raise HTTPException(
                422,
                detail={
                    "code": "LOGISTICA_NO_COINCIDE",
                    "message": "Logística no coincide",
                    "etiqueta_logistica": logistica_etiq.nombre if logistica_etiq else "Desconocida",
                    "etiqueta_logistica_id": etiqueta.logistica_id,
                    "pistoleando_logistica": logistica_pistoleando.nombre,
                    "pistoleando_logistica_id": payload.logistica_id,
                },
            )
    elif etiqueta.logistica_id is None and logistica_pistoleando.pistoleado_asigna:
        # Sin logística asignada + modo asignación → asignar
        etiqueta.logistica_id = payload.logistica_id
        fue_asignada = True
    elif etiqueta.logistica_id is None and not logistica_pistoleando.pistoleado_asigna:
        if payload.forzar_asignacion:
            # Doble escaneo: el operador confirmó asignar esta logística
            etiqueta.logistica_id = payload.logistica_id
            fue_asignada = True
        else:
            # Sin logística asignada + modo estricto → rechazar (primer escaneo)
            raise HTTPException(
                422,
                detail={
                    "code": "SIN_LOGISTICA",
                    "message": "Etiqueta sin logística asignada",
                    "etiqueta_logistica": "Sin asignar",
                    "etiqueta_logistica_id": None,
                    "pistoleando_logistica": logistica_pistoleando.nombre,
                    "pistoleando_logistica_id": payload.logistica_id,
                },
            )

    ahora = datetime.now(UTC)

    # --- Per-bulto tracking (solo envíos manuales multi-bulto) ---
    is_multi_bulto = payload.bulto is not None and payload.total_bultos is not None and payload.total_bultos > 1
    bultos_pistoleados_count = 0

    if is_multi_bulto:
        # Parsear array existente de bultos pistoleados
        bultos_arr: list[dict] = []
        if etiqueta.pistoleado_bultos:
            try:
                bultos_arr = json.loads(etiqueta.pistoleado_bultos)
            except (json.JSONDecodeError, TypeError):
                bultos_arr = []

        # Check duplicado de ESTE bulto específico
        bultos_ya_escaneados = {b["bulto"] for b in bultos_arr if "bulto" in b}
        if payload.bulto in bultos_ya_escaneados:
            # Buscar quién lo pistoleó
            entry_previo = next((b for b in bultos_arr if b.get("bulto") == payload.bulto), None)
            op_previo_id = entry_previo.get("operador_id") if entry_previo else None
            op_previo = db.query(Operador).filter(Operador.id == op_previo_id).first() if op_previo_id else None
            nombre_previo = op_previo.nombre if op_previo else "Desconocido"
            raise HTTPException(
                409,
                detail={
                    "code": "YA_PISTOLEADA",
                    "message": f"Bulto {payload.bulto}/{payload.total_bultos} ya pistoleado",
                    "pistoleado_por": nombre_previo,
                    "pistoleado_at": entry_previo.get("at", "") if entry_previo else "",
                    "pistoleado_caja": entry_previo.get("caja", "") if entry_previo else "",
                },
            )

        # Appendear nuevo bulto
        bultos_arr.append(
            {
                "bulto": payload.bulto,
                "at": ahora.isoformat(),
                "caja": payload.caja,
                "operador_id": payload.operador_id,
            }
        )
        etiqueta.pistoleado_bultos = json.dumps(bultos_arr, separators=(",", ":"))
        bultos_pistoleados_count = len(bultos_arr)

        # Guardar total_bultos en la etiqueta si no estaba
        if etiqueta.total_bultos is None:
            etiqueta.total_bultos = payload.total_bultos

        # Cuando TODOS los bultos fueron escaneados → marcar pistoleado_at (backward compat)
        if bultos_pistoleados_count >= payload.total_bultos:
            etiqueta.pistoleado_at = ahora
            etiqueta.pistoleado_caja = payload.caja
            etiqueta.pistoleado_operador_id = payload.operador_id
    else:
        # --- Comportamiento original: bulto único / ML etiquetas ---
        if etiqueta.pistoleado_at is not None:
            op_previo = db.query(Operador).filter(Operador.id == etiqueta.pistoleado_operador_id).first()
            nombre_previo = op_previo.nombre if op_previo else "Desconocido"
            raise HTTPException(
                409,
                detail={
                    "code": "YA_PISTOLEADA",
                    "message": "Ya pistoleada",
                    "pistoleado_por": nombre_previo,
                    "pistoleado_at": str(etiqueta.pistoleado_at),
                    "pistoleado_caja": etiqueta.pistoleado_caja or "",
                },
            )

        etiqueta.pistoleado_at = ahora
        etiqueta.pistoleado_caja = payload.caja
        etiqueta.pistoleado_operador_id = payload.operador_id
        bultos_pistoleados_count = 1

    # Registrar actividad
    detalle_actividad: dict = {
        "shipping_id": payload.shipping_id,
        "caja": payload.caja,
        "logistica_id": payload.logistica_id,
        "fecha_envio": str(etiqueta.fecha_envio) if etiqueta.fecha_envio else None,
    }
    if is_multi_bulto:
        detalle_actividad["bulto"] = payload.bulto
        detalle_actividad["total_bultos"] = payload.total_bultos
        detalle_actividad["bultos_pistoleados"] = bultos_pistoleados_count

    actividad = OperadorActividad(
        operador_id=payload.operador_id,
        usuario_id=current_user.id,
        tab_key="pistoleado",
        accion="pistoleado",
        detalle=detalle_actividad,
    )
    db.add(actividad)

    db.commit()
    sse_publish_bg("etiquetas:changed", {"hint": "reload"})

    # Obtener datos de ML shipping para el feedback
    ml_shipping = (
        db.query(MercadoLibreOrderShipping)
        .filter(
            MercadoLibreOrderShipping.mlshippingid == payload.shipping_id,
        )
        .first()
    )

    # Obtener cordón
    cordon_val = None
    if ml_shipping and ml_shipping.mlzip_code:
        cordon_row = (
            db.query(CodigoPostalCordon.cordon)
            .filter(
                CodigoPostalCordon.codigo_postal == ml_shipping.mlzip_code,
            )
            .first()
        )
        cordon_val = cordon_row.cordon if cordon_row else None

    # Obtener estado ERP del pedido (via soh_sub → SaleOrderStatus)
    estado_erp_name = None
    if ml_shipping and ml_shipping.mlo_id:
        soh_row = (
            db.query(SaleOrderHeader.ssos_id)
            .filter(SaleOrderHeader.mlo_id == ml_shipping.mlo_id)
            .order_by(desc(SaleOrderHeader.soh_cd))
            .first()
        )
        if soh_row and soh_row.ssos_id:
            ssos_row = db.query(SaleOrderStatus.ssos_name).filter(SaleOrderStatus.ssos_id == soh_row.ssos_id).first()
            estado_erp_name = ssos_row.ssos_name if ssos_row else None

    # Contar pistoleadas de este operador + logística + fecha (para TTS counter)
    count = (
        db.query(func.count())
        .select_from(EtiquetaEnvio)
        .filter(
            EtiquetaEnvio.pistoleado_operador_id == payload.operador_id,
            EtiquetaEnvio.logistica_id == payload.logistica_id,
            EtiquetaEnvio.pistoleado_at.isnot(None),
            func.date(EtiquetaEnvio.pistoleado_at) == date.today(),
        )
        .scalar()
        or 0
    )

    return PistolearResponse(
        ok=True,
        shipping_id=payload.shipping_id,
        caja=payload.caja,
        operador=operador.nombre,
        receiver_name=ml_shipping.mlreceiver_name if ml_shipping else None,
        ciudad=ml_shipping.mlcity_name if ml_shipping else None,
        cordon=cordon_val,
        pistoleado_at=str(ahora),
        bulto=payload.bulto,
        total_bultos=payload.total_bultos,
        bultos_pistoleados=bultos_pistoleados_count,
        count=count,
        estado_erp=estado_erp_name,
        logistica_asignada=fue_asignada,
    )


@router.get(
    "/etiquetas-envio/pistoleado/stats",
    response_model=PistoleadoStatsResponse,
    summary="Estadísticas de pistoleado por fecha y logística",
)
def stats_pistoleado(
    fecha: Optional[date] = Query(None, description="Fecha de envío (default: hoy)"),
    logistica_id: Optional[int] = Query(None, description="Filtrar por logística"),
    db: Session = Depends(get_db),
    current_user: Usuario = Depends(get_current_user),
) -> PistoleadoStatsResponse:
    """
    Estadísticas de pistoleado: total, pistoleadas, pendientes, porcentaje,
    desglose por caja y por operador.
    """
    _check_permiso(db, current_user, "envios_flex.pistoleado")

    fecha_filtro = fecha or date.today()

    # Base query: etiquetas de la fecha
    base = db.query(EtiquetaEnvio).filter(EtiquetaEnvio.fecha_envio == fecha_filtro)

    if logistica_id is not None:
        base = base.filter(EtiquetaEnvio.logistica_id == logistica_id)

    total = base.count()
    pistoleadas = base.filter(EtiquetaEnvio.pistoleado_at.isnot(None)).count()
    pendientes = total - pistoleadas
    porcentaje = round((pistoleadas / total * 100), 1) if total > 0 else 0.0

    # Por caja
    caja_rows = db.query(
        EtiquetaEnvio.pistoleado_caja,
        func.count().label("cantidad"),
    ).filter(
        EtiquetaEnvio.fecha_envio == fecha_filtro,
        EtiquetaEnvio.pistoleado_at.isnot(None),
        EtiquetaEnvio.pistoleado_caja.isnot(None),
    )
    if logistica_id is not None:
        caja_rows = caja_rows.filter(EtiquetaEnvio.logistica_id == logistica_id)
    caja_rows = caja_rows.group_by(EtiquetaEnvio.pistoleado_caja).all()
    por_caja = {row.pistoleado_caja: row.cantidad for row in caja_rows}

    # Por operador
    op_rows = (
        db.query(
            Operador.nombre,
            func.count().label("cantidad"),
        )
        .join(EtiquetaEnvio, EtiquetaEnvio.pistoleado_operador_id == Operador.id)
        .filter(
            EtiquetaEnvio.fecha_envio == fecha_filtro,
            EtiquetaEnvio.pistoleado_at.isnot(None),
        )
    )
    if logistica_id is not None:
        op_rows = op_rows.filter(EtiquetaEnvio.logistica_id == logistica_id)
    op_rows = op_rows.group_by(Operador.nombre).all()
    por_operador = {row.nombre: row.cantidad for row in op_rows}

    # Pistoleadas cuyo pedido ERP está "En Preparación"
    # shipping_id → MercadoLibreOrderShipping.mlshippingid → mlo_id
    # → SaleOrderHeader.mlo_id → ssos_id → SaleOrderStatus.ssos_name
    ssos_preparacion = db.query(SaleOrderStatus.ssos_id).filter(SaleOrderStatus.ssos_name == "En Preparación").first()
    en_preparacion = 0
    if ssos_preparacion:
        en_prep_q = (
            db.query(func.count())
            .select_from(EtiquetaEnvio)
            .join(
                MercadoLibreOrderShipping,
                MercadoLibreOrderShipping.mlshippingid == EtiquetaEnvio.shipping_id,
            )
            .join(
                SaleOrderHeader,
                SaleOrderHeader.mlo_id == MercadoLibreOrderShipping.mlo_id,
            )
            .filter(
                EtiquetaEnvio.fecha_envio == fecha_filtro,
                EtiquetaEnvio.pistoleado_at.isnot(None),
                SaleOrderHeader.ssos_id == ssos_preparacion.ssos_id,
            )
        )
        if logistica_id is not None:
            en_prep_q = en_prep_q.filter(EtiquetaEnvio.logistica_id == logistica_id)
        en_preparacion = en_prep_q.scalar() or 0

    return PistoleadoStatsResponse(
        total_etiquetas=total,
        pistoleadas=pistoleadas,
        pendientes=pendientes,
        porcentaje=porcentaje,
        en_preparacion=en_preparacion,
        por_caja=por_caja,
        por_operador=por_operador,
    )


@router.delete(
    "/etiquetas-envio/pistolear/{shipping_id}",
    response_model=dict,
    summary="Deshacer pistoleado (ANULAR)",
)
def deshacer_pistoleado(
    shipping_id: str,
    operador_id: int = Query(..., description="Operador que ejecuta la anulación"),
    db: Session = Depends(get_db),
    current_user: Usuario = Depends(get_current_user),
) -> dict:
    """
    Revierte un pistoleado por error (comando ANULAR).
    Pone pistoleado_at, pistoleado_caja, pistoleado_operador_id en NULL.
    Registra actividad 'despistoleado' con el estado anterior.
    """
    _check_permiso(db, current_user, "envios_flex.pistoleado")

    # Validar operador activo
    operador = (
        db.query(Operador)
        .filter(
            Operador.id == operador_id,
            Operador.activo.is_(True),
        )
        .first()
    )
    if not operador:
        raise HTTPException(404, "Operador no encontrado o inactivo")

    etiqueta = (
        db.query(EtiquetaEnvio)
        .filter(
            EtiquetaEnvio.shipping_id == shipping_id,
        )
        .first()
    )
    if not etiqueta:
        raise HTTPException(404, f"Etiqueta {shipping_id} no encontrada")

    if etiqueta.pistoleado_at is None:
        raise HTTPException(400, f"Etiqueta {shipping_id} no está pistoleada")

    # Guardar estado anterior para auditoría
    op_previo = db.query(Operador).filter(Operador.id == etiqueta.pistoleado_operador_id).first()
    estado_anterior = {
        "shipping_id": shipping_id,
        "pistoleado_at": str(etiqueta.pistoleado_at),
        "pistoleado_caja": etiqueta.pistoleado_caja,
        "pistoleado_operador_id": etiqueta.pistoleado_operador_id,
        "pistoleado_operador_nombre": op_previo.nombre if op_previo else None,
    }

    # Limpiar pistoleado
    etiqueta.pistoleado_at = None
    etiqueta.pistoleado_caja = None
    etiqueta.pistoleado_operador_id = None

    # Registrar actividad
    actividad = OperadorActividad(
        operador_id=operador_id,
        usuario_id=current_user.id,
        tab_key="pistoleado",
        accion="despistoleado",
        detalle=estado_anterior,
    )
    db.add(actividad)

    db.commit()
    sse_publish_bg("etiquetas:changed", {"hint": "reload"})

    return {"ok": True, "shipping_id": shipping_id, "anulado_por": operador.nombre}
