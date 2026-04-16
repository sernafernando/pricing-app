"""
Endpoints de estadísticas y cache de envíos Turbo.
"""

import logging
from datetime import datetime

from fastapi import APIRouter, Depends, Query, HTTPException
from sqlalchemy import func
from sqlalchemy.orm import Session

from app.core.database import get_db, get_async_db
from app.api.deps import get_current_user
from app.models.motoquero import Motoquero
from app.models.zona_reparto import ZonaReparto
from app.models.asignacion_turbo import AsignacionTurbo
from app.models.mercadolibre_order_shipping import MercadoLibreOrderShipping
from app.services.permisos_service import verificar_permiso

from ._shared import (
    ARGENTINA_TZ,
    DeleteResponse,
    EstadisticasResponse,
    _envios_cache,
    obtener_envios_desde_erp,
)

router = APIRouter()
logger = logging.getLogger(__name__)


@router.get("/turbo/estadisticas", response_model=EstadisticasResponse)
async def obtener_estadisticas(
    db: Session = Depends(get_async_db),
    current_user: dict = Depends(get_current_user),
    dias_atras: int = Query(7, ge=1, le=90, description="Días hacia atrás para consultar scriptEnvios"),
):
    """
    Obtiene estadísticas generales del sistema de Turbo Routing.

    IMPORTANTE: Usa scriptEnvios para contar envíos pendientes REALES (no datos stale).
    """
    if not verificar_permiso(db, current_user, "ordenes.gestionar_turbo_routing"):
        raise HTTPException(status_code=403, detail="Sin permiso")

    # 1. Obtener solo IDs de envíos Turbo desde BD (query optimizada)
    turbo_ids_query = (
        db.query(MercadoLibreOrderShipping.mlshippingid)
        .filter(MercadoLibreOrderShipping.mlshipping_method_id == "515282")
        .all()
    )
    turbo_ids_set = {str(sid[0]) for sid in turbo_ids_query}

    # 2. Obtener datos actualizados desde scriptEnvios (CON CACHE)
    envios_erp = await obtener_envios_desde_erp(dias_atras)

    # 3. Pre-filtrar scriptEnvios: solo estados pendientes
    envios_pendientes_erp = [e for e in envios_erp if e.get("Estado", "").lower() in ["ready_to_ship", "not_delivered"]]

    # 4. Contar envíos Turbo pendientes (cruce optimizado con set)
    envios_pendientes_ids = {
        str(e.get("Número de Envío", ""))
        for e in envios_pendientes_erp
        if str(e.get("Número de Envío", "")) in turbo_ids_set
    }

    # 5. Filtrar asignados (query optimizada con set)
    asignados_ids_query = db.query(AsignacionTurbo.mlshippingid).filter(AsignacionTurbo.estado != "cancelado").all()
    asignados_ids_set = {str(a[0]) for a in asignados_ids_query}

    # Contar solo los NO asignados (operación de sets: O(n) en lugar de O(n²))
    total_pendientes = len(envios_pendientes_ids - asignados_ids_set)

    # Total asignados
    total_asignados = len(asignados_ids_set)

    # Motoqueros activos
    total_motoqueros = db.query(func.count(Motoquero.id)).filter(Motoquero.activo.is_(True)).scalar() or 0

    # Zonas activas
    total_zonas = db.query(func.count(ZonaReparto.id)).filter(ZonaReparto.activa.is_(True)).scalar() or 0

    # Asignaciones hoy (fecha actual en Argentina)
    hoy_inicio = datetime.now(ARGENTINA_TZ).replace(hour=0, minute=0, second=0, microsecond=0)
    asignaciones_hoy = (
        db.query(func.count(AsignacionTurbo.id))
        .filter(AsignacionTurbo.asignado_at >= hoy_inicio, AsignacionTurbo.estado != "cancelado")
        .scalar()
        or 0
    )

    return EstadisticasResponse(
        total_envios_pendientes=total_pendientes,
        total_envios_asignados=total_asignados,
        total_motoqueros_activos=total_motoqueros,
        total_zonas_activas=total_zonas,
        asignaciones_hoy=asignaciones_hoy,
    )


@router.post("/turbo/cache/invalidar", response_model=DeleteResponse)
def invalidar_cache_envios(db: Session = Depends(get_db), current_user: dict = Depends(get_current_user)):
    """
    Invalida el cache de scriptEnvios para forzar actualización inmediata.
    Útil después de asignar envíos o cuando se necesitan datos frescos.
    """
    if not verificar_permiso(db, current_user, "ordenes.gestionar_turbo_routing"):
        raise HTTPException(status_code=403, detail="Sin permiso")

    _envios_cache["timestamp"] = None
    _envios_cache["data"] = []

    return DeleteResponse(message="Cache invalidado correctamente", success=True)
