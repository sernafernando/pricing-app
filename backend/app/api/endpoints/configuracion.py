from fastapi import APIRouter, Depends, HTTPException
from sqlalchemy.orm import Session
from sqlalchemy import and_, or_
from typing import List, Optional
from pydantic import BaseModel
from datetime import date
from app.core.database import get_db
from app.api.deps import get_current_user, require_role
from app.models.usuario import Usuario, RolUsuario
from app.models.pricing_constants import PricingConstants

router = APIRouter()

class PricingConstantsResponse(BaseModel):
    id: int
    monto_tier1: float
    monto_tier2: float
    monto_tier3: float
    comision_tier1: float
    comision_tier2: float
    comision_tier3: float
    varios_porcentaje: float
    grupo_comision_default: int
    markup_adicional_cuotas: float
    comision_tienda_nube: float
    comision_tienda_nube_tarjeta: Optional[float] = 3.0
    fecha_desde: date
    fecha_hasta: Optional[date]

class PricingConstantsCreate(BaseModel):
    monto_tier1: float
    monto_tier2: float
    monto_tier3: float
    comision_tier1: float
    comision_tier2: float
    comision_tier3: float
    varios_porcentaje: float
    grupo_comision_default: int
    markup_adicional_cuotas: float
    comision_tienda_nube: float = 1.0
    comision_tienda_nube_tarjeta: float = 3.0
    fecha_desde: date

@router.get("/pricing-constants", response_model=List[PricingConstantsResponse])
async def listar_pricing_constants(
    db: Session = Depends(get_db),
    current_user: Usuario = Depends(require_role([RolUsuario.ADMIN, RolUsuario.SUPERADMIN]))
):
    """Lista todas las versiones de constantes de pricing"""
    constants = db.query(PricingConstants).order_by(PricingConstants.fecha_desde.desc()).all()
    return constants

@router.get("/pricing-constants/actual")
async def obtener_pricing_constants_actual(
    db: Session = Depends(get_db),
    current_user: Usuario = Depends(get_current_user)
):
    """Obtiene las constantes de pricing vigentes para hoy"""
    hoy = date.today()
    constants = db.query(PricingConstants).filter(
        and_(
            PricingConstants.fecha_desde <= hoy,
            or_(
                PricingConstants.fecha_hasta.is_(None),
                PricingConstants.fecha_hasta >= hoy
            )
        )
    ).order_by(PricingConstants.fecha_desde.desc()).first()

    if not constants:
        raise HTTPException(status_code=404, detail="No se encontraron constantes de pricing vigentes")

    return {
        "monto_tier1": float(constants.monto_tier1),
        "monto_tier2": float(constants.monto_tier2),
        "monto_tier3": float(constants.monto_tier3),
        "comision_tier1": float(constants.comision_tier1),
        "comision_tier2": float(constants.comision_tier2),
        "comision_tier3": float(constants.comision_tier3),
        "varios_porcentaje": float(constants.varios_porcentaje),
        "grupo_comision_default": constants.grupo_comision_default,
        "markup_adicional_cuotas": float(constants.markup_adicional_cuotas),
        "comision_tienda_nube": float(constants.comision_tienda_nube),
        "comision_tienda_nube_tarjeta": float(constants.comision_tienda_nube_tarjeta) if constants.comision_tienda_nube_tarjeta else 3.0
    }

@router.post("/pricing-constants")
async def crear_pricing_constants(
    data: PricingConstantsCreate,
    db: Session = Depends(get_db),
    current_user: Usuario = Depends(require_role([RolUsuario.ADMIN, RolUsuario.SUPERADMIN]))
):
    """Crea una nueva versión de constantes de pricing"""

    # Verificar que no exista ya una versión para esa fecha
    existing = db.query(PricingConstants).filter(
        PricingConstants.fecha_desde == data.fecha_desde
    ).first()

    if existing:
        raise HTTPException(
            status_code=400,
            detail=f"Ya existe una versión de constantes para la fecha {data.fecha_desde}"
        )

    # Si hay versiones vigentes, cerrarlas
    versiones_vigentes = db.query(PricingConstants).filter(
        and_(
            PricingConstants.fecha_desde < data.fecha_desde,
            PricingConstants.fecha_hasta.is_(None)
        )
    ).all()

    for version in versiones_vigentes:
        version.fecha_hasta = data.fecha_desde

    # Crear nueva versión
    nueva_version = PricingConstants(
        monto_tier1=data.monto_tier1,
        monto_tier2=data.monto_tier2,
        monto_tier3=data.monto_tier3,
        comision_tier1=data.comision_tier1,
        comision_tier2=data.comision_tier2,
        comision_tier3=data.comision_tier3,
        varios_porcentaje=data.varios_porcentaje,
        grupo_comision_default=data.grupo_comision_default,
        markup_adicional_cuotas=data.markup_adicional_cuotas,
        comision_tienda_nube=data.comision_tienda_nube,
        comision_tienda_nube_tarjeta=data.comision_tienda_nube_tarjeta,
        fecha_desde=data.fecha_desde,
        creado_por=current_user.id
    )

    db.add(nueva_version)
    db.commit()
    db.refresh(nueva_version)

    return {"mensaje": "Constantes de pricing creadas correctamente", "id": nueva_version.id}

@router.delete("/pricing-constants/{id}")
async def eliminar_pricing_constants(
    id: int,
    db: Session = Depends(get_db),
    current_user: Usuario = Depends(require_role([RolUsuario.ADMIN, RolUsuario.SUPERADMIN]))
):
    """Elimina una versión de constantes de pricing"""
    constants = db.query(PricingConstants).filter(PricingConstants.id == id).first()

    if not constants:
        raise HTTPException(status_code=404, detail="Constantes no encontradas")

    # No permitir eliminar si es la única versión
    total_versiones = db.query(PricingConstants).count()
    if total_versiones <= 1:
        raise HTTPException(
            status_code=400,
            detail="No se puede eliminar la última versión de constantes"
        )

    db.delete(constants)
    db.commit()

    return {"mensaje": "Constantes eliminadas correctamente"}
