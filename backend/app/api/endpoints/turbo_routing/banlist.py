"""
Endpoints de banlist de envíos Turbo.
"""

import logging

from fastapi import APIRouter, Depends, Query, HTTPException
from sqlalchemy import func
from sqlalchemy.orm import Session

from app.core.database import get_db
from app.api.deps import get_current_user
from app.models.envio_turbo_banlist import EnvioTurboBanlist
from app.models.usuario import Usuario
from app.services.permisos_service import verificar_permiso

from ._shared import (
    BanearEnvioRequest,
    convert_to_argentina_tz,
)

router = APIRouter()
logger = logging.getLogger(__name__)


@router.get("/turbo/banlist")
def listar_envios_baneados(
    db: Session = Depends(get_db),
    current_user: dict = Depends(get_current_user),
    limit: int = Query(100, ge=1, le=500),
    offset: int = Query(0, ge=0),
):
    """
    Lista todos los envíos en la banlist (excluidos del sistema).
    """
    if not verificar_permiso(db, current_user, "ordenes.gestionar_turbo_routing"):
        raise HTTPException(status_code=403, detail="Sin permiso para gestionar Turbo Routing")

    banlist = (
        db.query(EnvioTurboBanlist).order_by(EnvioTurboBanlist.baneado_at.desc()).offset(offset).limit(limit).all()
    )

    total = db.query(func.count(EnvioTurboBanlist.id)).scalar()

    resultado = []
    for item in banlist:
        usuario = None
        if item.baneado_por:
            user_obj = db.query(Usuario).filter(Usuario.id == item.baneado_por).first()
            if user_obj:
                usuario = user_obj.nombre

        resultado.append(
            {
                "id": item.id,
                "mlshippingid": item.mlshippingid,
                "motivo": item.motivo,
                "notas": item.notas,
                "baneado_por": usuario,
                "baneado_at": convert_to_argentina_tz(item.baneado_at) if item.baneado_at else None,
            }
        )

    return {"items": resultado, "total": total, "limit": limit, "offset": offset}


@router.post("/turbo/banlist")
def banear_envio_turbo(
    request: BanearEnvioRequest, db: Session = Depends(get_db), current_user: dict = Depends(get_current_user)
):
    """
    Agrega un envío Turbo a la banlist para excluirlo del sistema.

    Casos de uso:
    - Estados buggeados (stuck en not_delivered por meses)
    - Inconsistencias con ML Webhook API
    - Duplicados o errores de sincronización
    """
    if not verificar_permiso(db, current_user, "ordenes.gestionar_turbo_routing"):
        raise HTTPException(status_code=403, detail="Sin permiso para gestionar Turbo Routing")

    # Verificar si ya existe
    existente = db.query(EnvioTurboBanlist).filter(EnvioTurboBanlist.mlshippingid == request.mlshippingid).first()

    if existente:
        raise HTTPException(status_code=400, detail=f"El envío {request.mlshippingid} ya está en la banlist")

    # Crear registro
    nuevo_ban = EnvioTurboBanlist(
        mlshippingid=request.mlshippingid,
        motivo=request.motivo,
        notas=request.notas,
        baneado_por=current_user.get("id"),
    )

    db.add(nuevo_ban)
    db.commit()
    db.refresh(nuevo_ban)

    logger.info(
        f"Envío {request.mlshippingid} agregado a banlist por usuario {current_user.get('nombre')}: {request.motivo}"
    )

    return {"success": True, "message": f"Envío {request.mlshippingid} agregado a la banlist", "id": nuevo_ban.id}


@router.delete("/turbo/banlist/{banlist_id}")
def desbanear_envio_turbo(
    banlist_id: int, db: Session = Depends(get_db), current_user: dict = Depends(get_current_user)
):
    """
    Quita un envío de la banlist (lo vuelve a habilitar en el sistema).
    """
    if not verificar_permiso(db, current_user, "ordenes.gestionar_turbo_routing"):
        raise HTTPException(status_code=403, detail="Sin permiso para gestionar Turbo Routing")

    ban = db.query(EnvioTurboBanlist).filter(EnvioTurboBanlist.id == banlist_id).first()

    if not ban:
        raise HTTPException(status_code=404, detail="Registro no encontrado en banlist")

    mlshippingid = ban.mlshippingid
    db.delete(ban)
    db.commit()

    logger.info(f"Envío {mlshippingid} removido de banlist por usuario {current_user.get('nombre')}")

    return {"success": True, "message": f"Envío {mlshippingid} removido de la banlist"}
