"""
Endpoints de asignación y toggle de atributos en etiquetas de envío.

Incluye:
- Asignar/desasignar logística (individual y masivo)
- Asignar/desasignar transporte (masivo)
- Cambiar fecha de envío
- Costo override
- Toggle turbo (individual y masivo)
- Toggle lluvia (individual y masivo)
- Flag de envío (individual y masivo)
- Retornado (individual y masivo)
"""

from datetime import datetime, UTC
from typing import Optional

from fastapi import APIRouter, Depends, HTTPException, Query
from sqlalchemy.orm import Session

from app.core.database import get_db
from app.core.sse import sse_publish_bg
from app.api.deps import get_current_user
from app.models.usuario import Usuario
from app.models.etiqueta_envio import EtiquetaEnvio
from app.models.logistica import Logistica
from app.models.transporte import Transporte
from app.models.operador import Operador
from app.models.operador_actividad import OperadorActividad

from app.api.endpoints.etiquetas_shared import (
    _check_permiso,
    _check_any_permiso,
    FLAG_ENVIO_VALIDOS,
    AsignarLogisticaRequest,
    AsignarMasivoRequest,
    AsignarTransporteMasivoRequest,
    CambiarFechaMasivoRequest,
    CambiarFechaRequest,
    CostoOverrideRequest,
    FlagEnvioMasivoRequest,
    FlagEnvioRequest,
    RetornadoMasivoRequest,
    ShippingIdsRequest,
)

router = APIRouter()


@router.put(
    "/etiquetas-envio/{shipping_id}/logistica",
    response_model=dict,
    summary="Asignar logística a una etiqueta",
)
def asignar_logistica(
    shipping_id: str,
    payload: AsignarLogisticaRequest,
    db: Session = Depends(get_db),
    current_user: Usuario = Depends(get_current_user),
) -> dict:
    """Asigna o desasigna la logística de una etiqueta."""
    _check_permiso(db, current_user, "envios_flex.asignar_logistica")

    etiqueta = db.query(EtiquetaEnvio).filter(EtiquetaEnvio.shipping_id == shipping_id).first()
    if not etiqueta:
        raise HTTPException(404, f"Etiqueta {shipping_id} no encontrada")

    if payload.logistica_id is not None:
        logistica = db.query(Logistica).filter(Logistica.id == payload.logistica_id, Logistica.activa.is_(True)).first()
        if not logistica:
            raise HTTPException(404, "Logística no encontrada o inactiva")

    etiqueta.logistica_id = payload.logistica_id
    db.commit()
    sse_publish_bg("etiquetas:changed", {"hint": "reload"})

    return {"ok": True, "shipping_id": shipping_id, "logistica_id": payload.logistica_id}


@router.put(
    "/etiquetas-envio/{shipping_id}/fecha",
    response_model=dict,
    summary="Cambiar fecha de envío (reprogramar)",
)
def cambiar_fecha(
    shipping_id: str,
    payload: CambiarFechaRequest,
    db: Session = Depends(get_db),
    current_user: Usuario = Depends(get_current_user),
) -> dict:
    """Reprograma la fecha de envío de una etiqueta."""
    _check_permiso(db, current_user, "envios_flex.cambiar_fecha")

    etiqueta = db.query(EtiquetaEnvio).filter(EtiquetaEnvio.shipping_id == shipping_id).first()
    if not etiqueta:
        raise HTTPException(404, f"Etiqueta {shipping_id} no encontrada")

    etiqueta.fecha_envio = payload.fecha_envio
    db.commit()
    sse_publish_bg("etiquetas:changed", {"hint": "reload"})

    return {"ok": True, "shipping_id": shipping_id, "fecha_envio": str(payload.fecha_envio)}


@router.put(
    "/etiquetas-envio/{shipping_id}/costo",
    response_model=dict,
    summary="Establecer o quitar costo override de una etiqueta",
)
def set_costo_override(
    shipping_id: str,
    payload: CostoOverrideRequest,
    db: Session = Depends(get_db),
    current_user: Usuario = Depends(get_current_user),
) -> dict:
    """
    Establece un costo manual (override) para una etiqueta de envío.

    Si costo es None, elimina el override y vuelve al costo calculado
    automáticamente por logistica_costo_cordon.

    Requiere envios_flex.config y operador autenticado con PIN.
    Registra la acción en operador_actividad para auditoría.
    """
    _check_permiso(db, current_user, "envios_flex.config")

    etiqueta = db.query(EtiquetaEnvio).filter(EtiquetaEnvio.shipping_id == shipping_id).first()
    if not etiqueta:
        raise HTTPException(404, f"Etiqueta {shipping_id} no encontrada")

    # Validar operador activo
    operador = db.query(Operador).filter(Operador.id == payload.operador_id, Operador.activo.is_(True)).first()
    if not operador:
        raise HTTPException(404, "Operador no encontrado o inactivo")

    valor_anterior = float(etiqueta.costo_override) if etiqueta.costo_override is not None else None
    etiqueta.costo_override = payload.costo

    # Registrar actividad del operador
    actividad = OperadorActividad(
        operador_id=payload.operador_id,
        usuario_id=current_user.id,
        tab_key="envios-flex",
        accion="costo_override",
        detalle={
            "shipping_id": shipping_id,
            "costo_anterior": valor_anterior,
            "costo_nuevo": payload.costo,
        },
    )
    db.add(actividad)

    db.commit()
    sse_publish_bg("etiquetas:changed", {"hint": "reload"})

    return {
        "ok": True,
        "shipping_id": shipping_id,
        "costo_override": payload.costo,
    }


@router.put(
    "/etiquetas-envio/asignar-masivo",
    response_model=dict,
    summary="Asignar logística a múltiples etiquetas",
)
def asignar_masivo(
    payload: AsignarMasivoRequest,
    db: Session = Depends(get_db),
    current_user: Usuario = Depends(get_current_user),
) -> dict:
    """Asigna la misma logística a un lote de etiquetas."""
    _check_permiso(db, current_user, "envios_flex.asignar_logistica")

    # Verificar que la logística existe
    logistica = db.query(Logistica).filter(Logistica.id == payload.logistica_id, Logistica.activa.is_(True)).first()
    if not logistica:
        raise HTTPException(404, "Logística no encontrada o inactiva")

    # Update masivo
    updated = (
        db.query(EtiquetaEnvio)
        .filter(EtiquetaEnvio.shipping_id.in_(payload.shipping_ids))
        .update(
            {EtiquetaEnvio.logistica_id: payload.logistica_id},
            synchronize_session="fetch",
        )
    )

    db.commit()
    sse_publish_bg("etiquetas:changed", {"hint": "reload"})

    return {
        "ok": True,
        "actualizadas": updated,
        "logistica_id": payload.logistica_id,
        "logistica_nombre": logistica.nombre,
    }


@router.put(
    "/etiquetas-envio/fecha-masivo",
    response_model=dict,
    summary="Cambiar fecha de envío masivamente",
)
def cambiar_fecha_masivo(
    payload: CambiarFechaMasivoRequest,
    db: Session = Depends(get_db),
    current_user: Usuario = Depends(get_current_user),
) -> dict:
    """
    Reprograma la fecha de envío de un lote de etiquetas en una sola transacción.

    Usa el mismo permiso que el endpoint individual de cambio de fecha.
    """
    _check_permiso(db, current_user, "envios_flex.cambiar_fecha")

    updated = (
        db.query(EtiquetaEnvio)
        .filter(EtiquetaEnvio.shipping_id.in_(payload.shipping_ids))
        .update(
            {EtiquetaEnvio.fecha_envio: payload.fecha_envio},
            synchronize_session="fetch",
        )
    )

    db.commit()
    sse_publish_bg("etiquetas:changed", {"hint": "reload"})

    return {
        "ok": True,
        "actualizadas": updated,
        "fecha_envio": str(payload.fecha_envio),
    }


@router.put(
    "/etiquetas-envio/{shipping_id}/turbo",
    response_model=dict,
    summary="Marcar o desmarcar envío como turbo",
)
def toggle_turbo(
    shipping_id: str,
    es_turbo: bool = Query(..., description="True para marcar como turbo, False para desmarcar"),
    db: Session = Depends(get_db),
    current_user: Usuario = Depends(get_current_user),
) -> dict:
    """
    Marca o desmarca una etiqueta como turbo (mlshipping_method_id = '515282').

    Requiere permiso envios_flex.asignar_turbo.
    """
    _check_permiso(db, current_user, "envios_flex.asignar_turbo")

    etiqueta = db.query(EtiquetaEnvio).filter(EtiquetaEnvio.shipping_id == shipping_id).first()
    if not etiqueta:
        raise HTTPException(404, f"Etiqueta {shipping_id} no encontrada")

    valor_anterior = etiqueta.es_turbo
    etiqueta.es_turbo = es_turbo
    db.commit()
    sse_publish_bg("etiquetas:changed", {"hint": "reload"})

    return {
        "ok": True,
        "shipping_id": shipping_id,
        "es_turbo": es_turbo,
        "valor_anterior": valor_anterior,
    }


@router.put(
    "/etiquetas-envio/turbo-masivo",
    response_model=dict,
    summary="Marcar o desmarcar turbo en múltiples etiquetas",
)
def toggle_turbo_masivo(
    payload: ShippingIdsRequest,
    es_turbo: bool = Query(..., description="True para marcar como turbo, False para desmarcar"),
    db: Session = Depends(get_db),
    current_user: Usuario = Depends(get_current_user),
) -> dict:
    """
    Marca o desmarca múltiples etiquetas como turbo en una sola operación.

    Requiere permiso envios_flex.asignar_turbo.
    """
    _check_permiso(db, current_user, "envios_flex.asignar_turbo")

    updated = (
        db.query(EtiquetaEnvio)
        .filter(EtiquetaEnvio.shipping_id.in_(payload.shipping_ids))
        .update({EtiquetaEnvio.es_turbo: es_turbo}, synchronize_session="fetch")
    )
    db.commit()
    sse_publish_bg("etiquetas:changed", {"hint": "reload"})

    return {
        "ok": True,
        "es_turbo": es_turbo,
        "actualizados": updated,
        "solicitados": len(payload.shipping_ids),
    }


@router.put(
    "/etiquetas-envio/{shipping_id}/lluvia",
    response_model=dict,
    summary="Marcar o desmarcar envío como lluvia",
)
def toggle_lluvia(
    shipping_id: str,
    es_lluvia: bool = Query(..., description="True para marcar como lluvia, False para desmarcar"),
    db: Session = Depends(get_db),
    current_user: Usuario = Depends(get_current_user),
) -> dict:
    """
    Marca o desmarca una etiqueta como lluvia (offset sobre costo turbo).

    Solo aplica cuando la etiqueta también es turbo.
    Requiere permiso envios_flex.asignar_lluvia.
    """
    _check_permiso(db, current_user, "envios_flex.asignar_lluvia")

    etiqueta = db.query(EtiquetaEnvio).filter(EtiquetaEnvio.shipping_id == shipping_id).first()
    if not etiqueta:
        raise HTTPException(404, f"Etiqueta {shipping_id} no encontrada")

    valor_anterior = etiqueta.es_lluvia
    etiqueta.es_lluvia = es_lluvia
    db.commit()
    sse_publish_bg("etiquetas:changed", {"hint": "reload"})

    return {
        "ok": True,
        "shipping_id": shipping_id,
        "es_lluvia": es_lluvia,
        "valor_anterior": valor_anterior,
    }


@router.put(
    "/etiquetas-envio/lluvia-masivo",
    response_model=dict,
    summary="Marcar o desmarcar lluvia en múltiples etiquetas",
)
def toggle_lluvia_masivo(
    payload: ShippingIdsRequest,
    es_lluvia: bool = Query(..., description="True para marcar como lluvia, False para desmarcar"),
    db: Session = Depends(get_db),
    current_user: Usuario = Depends(get_current_user),
) -> dict:
    """
    Marca o desmarca múltiples etiquetas como lluvia en una sola operación.

    Requiere permiso envios_flex.asignar_lluvia.
    """
    _check_permiso(db, current_user, "envios_flex.asignar_lluvia")

    updated = (
        db.query(EtiquetaEnvio)
        .filter(EtiquetaEnvio.shipping_id.in_(payload.shipping_ids))
        .update({EtiquetaEnvio.es_lluvia: es_lluvia}, synchronize_session="fetch")
    )
    db.commit()
    sse_publish_bg("etiquetas:changed", {"hint": "reload"})

    return {
        "ok": True,
        "es_lluvia": es_lluvia,
        "actualizados": updated,
        "solicitados": len(payload.shipping_ids),
    }


# ── Flag de envío (mal pasado, cancelado, duplicado, otro) ───────


@router.put(
    "/etiquetas-envio/{shipping_id}/flag",
    response_model=dict,
    summary="Flaggear o desflaggear un envío",
)
def toggle_flag_envio(
    shipping_id: str,
    payload: FlagEnvioRequest,
    db: Session = Depends(get_db),
    current_user: Usuario = Depends(get_current_user),
) -> dict:
    """
    Marca un envío con un flag (mal_pasado, envio_cancelado, duplicado, otro)
    o lo quita (flag_envio=None).

    Los envíos flaggeados se muestran con badge visual en TabEnviosFlex
    y se contabilizan separados en las estadísticas.

    Requiere permiso envios_flex.config O seguimiento_envios.flag.
    """
    _check_any_permiso(db, current_user, ["envios_flex.config", "seguimiento_envios.flag"])

    if payload.flag_envio and payload.flag_envio not in FLAG_ENVIO_VALIDOS:
        raise HTTPException(
            422,
            f"Flag inválido. Valores permitidos: {', '.join(sorted(FLAG_ENVIO_VALIDOS))}",
        )

    etiqueta = db.query(EtiquetaEnvio).filter(EtiquetaEnvio.shipping_id == shipping_id).first()
    if not etiqueta:
        raise HTTPException(404, f"Etiqueta {shipping_id} no encontrada")

    valor_anterior = etiqueta.flag_envio

    if payload.flag_envio:
        etiqueta.flag_envio = payload.flag_envio
        etiqueta.flag_envio_motivo = payload.motivo
        etiqueta.flag_envio_at = datetime.now(UTC)
        etiqueta.flag_envio_usuario_id = current_user.id
    else:
        # Quitar flag
        etiqueta.flag_envio = None
        etiqueta.flag_envio_motivo = None
        etiqueta.flag_envio_at = None
        etiqueta.flag_envio_usuario_id = None

    db.commit()
    sse_publish_bg("etiquetas:changed", {"hint": "reload"})

    return {
        "ok": True,
        "shipping_id": shipping_id,
        "flag_envio": etiqueta.flag_envio,
        "valor_anterior": valor_anterior,
    }


@router.put(
    "/etiquetas-envio/flag-masivo",
    response_model=dict,
    summary="Flaggear o desflaggear múltiples envíos",
)
def toggle_flag_envio_masivo(
    payload: FlagEnvioMasivoRequest,
    db: Session = Depends(get_db),
    current_user: Usuario = Depends(get_current_user),
) -> dict:
    """
    Marca o desmarca múltiples etiquetas con un flag en una sola operación.

    Requiere permiso envios_flex.config O seguimiento_envios.flag.
    """
    _check_any_permiso(db, current_user, ["envios_flex.config", "seguimiento_envios.flag"])

    if payload.flag_envio and payload.flag_envio not in FLAG_ENVIO_VALIDOS:
        raise HTTPException(
            422,
            f"Flag inválido. Valores permitidos: {', '.join(sorted(FLAG_ENVIO_VALIDOS))}",
        )

    update_values: dict = {}
    if payload.flag_envio:
        update_values = {
            EtiquetaEnvio.flag_envio: payload.flag_envio,
            EtiquetaEnvio.flag_envio_motivo: payload.motivo,
            EtiquetaEnvio.flag_envio_at: datetime.now(UTC),
            EtiquetaEnvio.flag_envio_usuario_id: current_user.id,
        }
    else:
        update_values = {
            EtiquetaEnvio.flag_envio: None,
            EtiquetaEnvio.flag_envio_motivo: None,
            EtiquetaEnvio.flag_envio_at: None,
            EtiquetaEnvio.flag_envio_usuario_id: None,
        }

    updated = (
        db.query(EtiquetaEnvio)
        .filter(EtiquetaEnvio.shipping_id.in_(payload.shipping_ids))
        .update(update_values, synchronize_session="fetch")
    )
    db.commit()
    sse_publish_bg("etiquetas:changed", {"hint": "reload"})

    return {
        "ok": True,
        "flag_envio": payload.flag_envio,
        "actualizados": updated,
        "solicitados": len(payload.shipping_ids),
    }


# ── Retornado (paquete devuelto a la oficina) ────────────────────


@router.put(
    "/etiquetas-envio/{shipping_id}/retornado",
    response_model=dict,
    summary="Marcar o desmarcar un envío como retornado",
)
def toggle_retornado(
    shipping_id: str,
    retornado: bool = True,
    db: Session = Depends(get_db),
    current_user: Usuario = Depends(get_current_user),
) -> dict:
    """
    Marca un envío como retornado (paquete devuelto físicamente a la oficina)
    o lo desmarca. Independiente del sistema de flags.

    Requiere permiso envios_flex.config O seguimiento_envios.marcar_retornado.
    """
    _check_any_permiso(db, current_user, ["envios_flex.config", "seguimiento_envios.marcar_retornado"])

    etiqueta = db.query(EtiquetaEnvio).filter(EtiquetaEnvio.shipping_id == shipping_id).first()
    if not etiqueta:
        raise HTTPException(404, f"Etiqueta {shipping_id} no encontrada")

    valor_anterior = etiqueta.retornado

    if retornado:
        etiqueta.retornado = True
        etiqueta.retornado_at = datetime.now(UTC)
        etiqueta.retornado_usuario_id = current_user.id
    else:
        etiqueta.retornado = None
        etiqueta.retornado_at = None
        etiqueta.retornado_usuario_id = None

    db.commit()
    sse_publish_bg("etiquetas:changed", {"hint": "reload"})

    return {
        "ok": True,
        "shipping_id": shipping_id,
        "retornado": etiqueta.retornado,
        "valor_anterior": valor_anterior,
    }


@router.put(
    "/etiquetas-envio/retornado-masivo",
    response_model=dict,
    summary="Marcar o desmarcar múltiples envíos como retornados",
)
def toggle_retornado_masivo(
    payload: RetornadoMasivoRequest,
    db: Session = Depends(get_db),
    current_user: Usuario = Depends(get_current_user),
) -> dict:
    """
    Marca o desmarca múltiples etiquetas como retornadas en una sola operación.

    Requiere permiso envios_flex.config O seguimiento_envios.marcar_retornado.
    """
    _check_any_permiso(db, current_user, ["envios_flex.config", "seguimiento_envios.marcar_retornado"])

    if payload.retornado:
        update_values = {
            EtiquetaEnvio.retornado: True,
            EtiquetaEnvio.retornado_at: datetime.now(UTC),
            EtiquetaEnvio.retornado_usuario_id: current_user.id,
        }
    else:
        update_values = {
            EtiquetaEnvio.retornado: None,
            EtiquetaEnvio.retornado_at: None,
            EtiquetaEnvio.retornado_usuario_id: None,
        }

    updated = (
        db.query(EtiquetaEnvio)
        .filter(EtiquetaEnvio.shipping_id.in_(payload.shipping_ids))
        .update(update_values, synchronize_session="fetch")
    )
    db.commit()
    sse_publish_bg("etiquetas:changed", {"hint": "reload"})

    return {
        "ok": True,
        "retornado": payload.retornado,
        "actualizados": updated,
        "solicitados": len(payload.shipping_ids),
    }


@router.put(
    "/etiquetas-envio/transporte-masivo",
    response_model=dict,
    summary="Asignar o quitar transporte a múltiples etiquetas",
)
def asignar_transporte_masivo(
    payload: AsignarTransporteMasivoRequest,
    db: Session = Depends(get_db),
    current_user: Usuario = Depends(get_current_user),
) -> dict:
    """
    Asigna (o desasigna) el mismo transporte a un lote de etiquetas.

    Si transporte_id es None, desasigna el transporte de todas las
    etiquetas indicadas.  Requiere permiso envios_flex.asignar_logistica.
    """
    _check_permiso(db, current_user, "envios_flex.asignar_logistica")

    transporte_nombre: Optional[str] = None
    if payload.transporte_id is not None:
        transporte = (
            db.query(Transporte).filter(Transporte.id == payload.transporte_id, Transporte.activa.is_(True)).first()
        )
        if not transporte:
            raise HTTPException(404, "Transporte no encontrado o inactivo")
        transporte_nombre = transporte.nombre

    updated = (
        db.query(EtiquetaEnvio)
        .filter(EtiquetaEnvio.shipping_id.in_(payload.shipping_ids))
        .update(
            {EtiquetaEnvio.transporte_id: payload.transporte_id},
            synchronize_session="fetch",
        )
    )
    db.commit()
    sse_publish_bg("etiquetas:changed", {"hint": "reload"})

    return {
        "ok": True,
        "actualizadas": updated,
        "transporte_id": payload.transporte_id,
        "transporte_nombre": transporte_nombre,
    }
