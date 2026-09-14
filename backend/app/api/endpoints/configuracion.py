from fastapi import APIRouter, Depends, HTTPException
from sqlalchemy.orm import Session
from sqlalchemy import and_, or_
from typing import List, Optional
from pydantic import BaseModel, Field
from datetime import date
from app.core.database import get_db
from app.api.deps import get_current_user, require_role
from app.models.usuario import Usuario, RolUsuario
from app.models.pricing_constants import PricingConstants
from app.models.varios_venta_pct import VariosVentaPct

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
    offset_flex: Optional[float] = None
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
    offset_flex: Optional[float] = None
    fecha_desde: date


@router.get("/pricing-constants", response_model=List[PricingConstantsResponse])
def listar_pricing_constants(
    db: Session = Depends(get_db),
    current_user: Usuario = Depends(require_role([RolUsuario.ADMIN, RolUsuario.SUPERADMIN])),
):
    """Lista todas las versiones de constantes de pricing"""
    constants = db.query(PricingConstants).order_by(PricingConstants.fecha_desde.desc()).all()
    return constants


@router.get("/pricing-constants/actual")
def obtener_pricing_constants_actual(db: Session = Depends(get_db), current_user: Usuario = Depends(get_current_user)):
    """Obtiene las constantes de pricing vigentes para hoy"""
    hoy = date.today()
    constants = (
        db.query(PricingConstants)
        .filter(
            and_(
                PricingConstants.fecha_desde <= hoy,
                or_(PricingConstants.fecha_hasta.is_(None), PricingConstants.fecha_hasta >= hoy),
            )
        )
        .order_by(PricingConstants.fecha_desde.desc())
        .first()
    )

    if not constants:
        raise HTTPException(status_code=404, detail="No se encontraron constantes de pricing vigentes")

    return {
        "id": constants.id,
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
        "comision_tienda_nube_tarjeta": float(constants.comision_tienda_nube_tarjeta)
        if constants.comision_tienda_nube_tarjeta
        else 3.0,
        "offset_flex": float(constants.offset_flex) if constants.offset_flex else None,
    }


@router.post("/pricing-constants")
def crear_pricing_constants(
    data: PricingConstantsCreate,
    db: Session = Depends(get_db),
    current_user: Usuario = Depends(require_role([RolUsuario.ADMIN, RolUsuario.SUPERADMIN])),
):
    """Crea una nueva versión de constantes de pricing"""

    # Verificar que no exista ya una versión para esa fecha
    existing = db.query(PricingConstants).filter(PricingConstants.fecha_desde == data.fecha_desde).first()

    if existing:
        raise HTTPException(
            status_code=400, detail=f"Ya existe una versión de constantes para la fecha {data.fecha_desde}"
        )

    # Si hay versiones vigentes, cerrarlas
    versiones_vigentes = (
        db.query(PricingConstants)
        .filter(and_(PricingConstants.fecha_desde < data.fecha_desde, PricingConstants.fecha_hasta.is_(None)))
        .all()
    )

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
        offset_flex=data.offset_flex,
        fecha_desde=data.fecha_desde,
        creado_por=current_user.id,
    )

    db.add(nueva_version)
    db.commit()
    db.refresh(nueva_version)

    return {"mensaje": "Constantes de pricing creadas correctamente", "id": nueva_version.id}


@router.put("/pricing-constants/{id}")
def actualizar_pricing_constants(
    id: int,
    data: PricingConstantsCreate,
    db: Session = Depends(get_db),
    current_user: Usuario = Depends(require_role([RolUsuario.ADMIN, RolUsuario.SUPERADMIN])),
):
    """Actualiza una versión existente de constantes de pricing"""
    constants = db.query(PricingConstants).filter(PricingConstants.id == id).first()

    if not constants:
        raise HTTPException(status_code=404, detail="Constantes no encontradas")

    # Si cambió la fecha_desde, verificar que no colisione con otra versión
    if data.fecha_desde != constants.fecha_desde:
        existing = (
            db.query(PricingConstants)
            .filter(PricingConstants.fecha_desde == data.fecha_desde, PricingConstants.id != id)
            .first()
        )
        if existing:
            raise HTTPException(
                status_code=400,
                detail=f"Ya existe una versión de constantes para la fecha {data.fecha_desde}",
            )

    constants.monto_tier1 = data.monto_tier1
    constants.monto_tier2 = data.monto_tier2
    constants.monto_tier3 = data.monto_tier3
    constants.comision_tier1 = data.comision_tier1
    constants.comision_tier2 = data.comision_tier2
    constants.comision_tier3 = data.comision_tier3
    constants.varios_porcentaje = data.varios_porcentaje
    constants.grupo_comision_default = data.grupo_comision_default
    constants.markup_adicional_cuotas = data.markup_adicional_cuotas
    constants.comision_tienda_nube = data.comision_tienda_nube
    constants.comision_tienda_nube_tarjeta = data.comision_tienda_nube_tarjeta
    constants.offset_flex = data.offset_flex

    db.commit()
    db.refresh(constants)

    return {"mensaje": "Constantes de pricing actualizadas correctamente", "id": constants.id}


@router.delete("/pricing-constants/{id}")
def eliminar_pricing_constants(
    id: int,
    db: Session = Depends(get_db),
    current_user: Usuario = Depends(require_role([RolUsuario.ADMIN, RolUsuario.SUPERADMIN])),
):
    """Elimina una versión de constantes de pricing.

    Si se elimina la versión vigente, reabre la versión anterior
    (le quita fecha_hasta) para que no quede un hueco sin constantes.
    """
    constants = db.query(PricingConstants).filter(PricingConstants.id == id).first()

    if not constants:
        raise HTTPException(status_code=404, detail="Constantes no encontradas")

    # No permitir eliminar si es la única versión
    total_versiones = db.query(PricingConstants).count()
    if total_versiones <= 1:
        raise HTTPException(status_code=400, detail="No se puede eliminar la última versión de constantes")

    # Detectar si es la versión vigente (sin fecha_hasta o fecha_hasta >= hoy)
    hoy = date.today()
    es_vigente = constants.fecha_hasta is None or constants.fecha_hasta >= hoy

    if es_vigente:
        # Buscar la versión anterior más reciente para reactivarla
        version_anterior = (
            db.query(PricingConstants)
            .filter(
                PricingConstants.id != id,
                PricingConstants.fecha_desde < constants.fecha_desde,
            )
            .order_by(PricingConstants.fecha_desde.desc())
            .first()
        )

        if not version_anterior:
            raise HTTPException(
                status_code=400,
                detail="No se puede eliminar la versión vigente sin una versión anterior que la reemplace",
            )

        # Reabrir la versión anterior
        version_anterior.fecha_hasta = None

    db.delete(constants)
    db.commit()

    return {"mensaje": "Constantes eliminadas correctamente"}


# ── "% de varios" del Total Gauss (ml-ventas-modo-logistico, PR5) ─────
#
# Reusa el PATRÓN de arriba (versionado por `fecha_desde`/`fecha_hasta`,
# el endpoint POST cierra la versión anterior), NO la fila de
# `pricing_constants.varios_porcentaje`: ese es una ESTIMACIÓN de
# impuestos + financiero + logística para presupuestar hacia adelante; en
# el desglose de una venta esos tres ya son datos REALES (SIRTAC,
# comisión de ML, flete), así que reusar la fila sería doble conteo.
# `services/ml_ventas_desglose/deducciones.VariosDeduccion` lee la
# versión vigente A LA FECHA DE LA VENTA, nunca la de hoy.


class VariosVentaPctResponse(BaseModel):
    id: int
    porcentaje: float
    fecha_desde: date
    fecha_hasta: Optional[date] = None

    model_config = {"from_attributes": True}


class VariosVentaPctCreate(BaseModel):
    # BOUNDED, because this multiplies against the net of EVERY sale in
    # force on that date. A typo of -5 or 500 would otherwise sail through
    # -- the column is `Numeric(5,2)`, so the database does not even stop
    # it until three digits. `CostoOverrideRequest.costo` in this same file
    # already uses `Field(ge=0)`; minimalism never applies to validation.
    porcentaje: float = Field(ge=0, le=100)
    fecha_desde: date


@router.get("/varios-venta-pct", response_model=List[VariosVentaPctResponse])
def listar_varios_venta_pct(
    db: Session = Depends(get_db),
    current_user: Usuario = Depends(require_role([RolUsuario.ADMIN, RolUsuario.SUPERADMIN])),
):
    """Lista todas las versiones del "% de varios" de ventas."""
    return db.query(VariosVentaPct).order_by(VariosVentaPct.fecha_desde.desc()).all()


@router.get("/varios-venta-pct/actual", response_model=VariosVentaPctResponse)
def obtener_varios_venta_pct_actual(db: Session = Depends(get_db), current_user: Usuario = Depends(get_current_user)):
    """Obtiene la versión vigente HOY -- una venta histórica NO usa este
    endpoint: lee la versión vigente a SU fecha vía `VariosDeduccion`."""
    hoy = date.today()
    version = (
        db.query(VariosVentaPct)
        .filter(
            and_(
                VariosVentaPct.fecha_desde <= hoy,
                or_(VariosVentaPct.fecha_hasta.is_(None), VariosVentaPct.fecha_hasta >= hoy),
            )
        )
        .order_by(VariosVentaPct.fecha_desde.desc())
        .first()
    )
    if not version:
        raise HTTPException(status_code=404, detail="No se encontró un % de varios vigente")
    return version


@router.post("/varios-venta-pct")
def crear_varios_venta_pct(
    data: VariosVentaPctCreate,
    db: Session = Depends(get_db),
    current_user: Usuario = Depends(require_role([RolUsuario.ADMIN, RolUsuario.SUPERADMIN])),
):
    """Crea una nueva versión del "% de varios", cerrando la vigente
    anterior -- mismo patrón que `crear_pricing_constants`."""
    existing = db.query(VariosVentaPct).filter(VariosVentaPct.fecha_desde == data.fecha_desde).first()
    if existing:
        raise HTTPException(
            status_code=400, detail=f"Ya existe una versión de % de varios para la fecha {data.fecha_desde}"
        )

    versiones_vigentes = (
        db.query(VariosVentaPct)
        .filter(and_(VariosVentaPct.fecha_desde < data.fecha_desde, VariosVentaPct.fecha_hasta.is_(None)))
        .all()
    )
    for version in versiones_vigentes:
        version.fecha_hasta = data.fecha_desde

    nueva_version = VariosVentaPct(
        porcentaje=data.porcentaje,
        fecha_desde=data.fecha_desde,
        creado_por=current_user.id,
    )
    db.add(nueva_version)
    db.commit()
    db.refresh(nueva_version)

    return {"mensaje": "% de varios creado correctamente", "id": nueva_version.id}
