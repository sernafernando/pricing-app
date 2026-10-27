from fastapi import APIRouter, Depends, HTTPException
from sqlalchemy.orm import Session
from sqlalchemy import and_, or_
from typing import List, Optional
from pydantic import BaseModel, Field
from datetime import date
from app.core.database import get_db
from app.api.deps import get_current_user, require_permiso, require_role
from app.models.usuario import Usuario, RolUsuario
from app.models.pricing_constants import PricingConstants
from app.models.varios_venta_pct import VariosVentaPct
from app.models.ml_orders_ops import MlOrdersOps
from app.models.ml_payments import MlPaymentCharge, MlPaymentOps
from app.models.ml_venta_impuesto_tratamiento import ImpuestoTratamientoVenta
from app.services.ml_ventas_desglose.breakdown_service import (
    is_recoverable_withholding,
    is_seller_charge,
    tax_label,
    withholding_kind,
)
from app.services.ml_ventas_desglose.tax_treatment import TaxTreatment

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
    # Read-only: gated by the same `ml_ops.ver` that guards the ML sales
    # view this modal lives in, NOT the new edit permission -- product
    # decision was "se pueda ver pero no editar sin el permiso".
    current_user: Usuario = Depends(require_permiso("ml_ops.ver")),
):
    """Lista todas las versiones del "% de varios" de ventas."""
    return db.query(VariosVentaPct).order_by(VariosVentaPct.fecha_desde.desc()).all()


@router.get("/varios-venta-pct/actual", response_model=VariosVentaPctResponse)
def obtener_varios_venta_pct_actual(
    db: Session = Depends(get_db),
    # Same read-only gate as the list endpoint -- see comment there.
    current_user: Usuario = Depends(require_permiso("ml_ops.ver")),
):
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
    # Writing a new version needs the NEW, separate `ml_ops.varios_editar`
    # permission -- `ml_ops.ver` (read) is deliberately NOT enough here.
    current_user: Usuario = Depends(require_permiso("ml_ops.varios_editar")),
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

    # Affected-order count (design D11, PR5.T7/T8): the same union of OLD
    # and NEW windows the `ml_venta_varios_pct` statement trigger enqueues
    # (design D3 statement-level scope) -- every closed version's window
    # stays a SUPERSET of its own narrowed replacement (old.fecha_desde is
    # always <= data.fecha_desde), so the union collapses to "every order
    # from the EARLIEST touched fecha_desde forward". No BackgroundTask: the
    # worker (PR2/PR3) drains the queue at batch speed on its own; this is
    # only the count reported back to the caller, computed independently of
    # whether the trigger actually fired (Postgres-only DDL, but this
    # endpoint must return a correct count on every environment).
    affected_from = min([data.fecha_desde] + [version.fecha_desde for version in versiones_vigentes])

    nueva_version = VariosVentaPct(
        porcentaje=data.porcentaje,
        fecha_desde=data.fecha_desde,
        creado_por=current_user.id,
    )
    db.add(nueva_version)
    db.commit()
    db.refresh(nueva_version)

    recalculando = db.query(MlOrdersOps).filter(MlOrdersOps.date_created >= affected_from).count()

    return {"mensaje": "% de varios creado correctamente", "id": nueva_version.id, "recalculando": recalculando}


# ── Impuestos de ML: descontados o informativos, por período ──────────
#
# ventas-ml-impuestos-informativos S1-S3. Mismo patrón que el "% de varios":
# versiones por `fecha_desde`/`fecha_hasta`, el POST cierra la versión abierta
# del MISMO impuesto. Una venta usa la versión vigente a SU fecha
# (`breakdown_service.informational_rule`); un impuesto sin versiones sigue la
# regla de siempre (SIRTAC informativo, el resto se descuenta). El trigger de
# `ml_venta_impuesto_tratamiento` re-encola las ventas guardadas del período.


class ImpuestoVentaVersionResponse(BaseModel):
    id: int
    informativo: bool
    fecha_desde: date
    fecha_hasta: Optional[date] = None

    model_config = {"from_attributes": True}


class ImpuestoVentaResponse(BaseModel):
    charge_name: str
    etiqueta: str
    informativo_por_defecto: bool
    informativo_hoy: bool
    versiones: List[ImpuestoVentaVersionResponse]


class ImpuestoVentaCreate(BaseModel):
    charge_name: str = Field(min_length=1, max_length=120)
    informativo: bool
    fecha_desde: date


class ImpuestoVentaCreateResponse(BaseModel):
    mensaje: str
    id: int
    recalculando: int


@router.get("/impuestos-venta", response_model=List[ImpuestoVentaResponse])
def listar_impuestos_venta(
    db: Session = Depends(get_db),
    # Same read-only gate as "% de varios": viewable with the ML sales view.
    current_user: Usuario = Depends(require_permiso("ml_ops.ver")),
):
    """Lista cada retención que ML cobró al vendedor (una por nombre exacto, o sea por provincia), con su
    tratamiento por defecto, el vigente hoy y sus versiones, más los impuestos que solo tienen versiones."""
    vistos = {
        name
        for (name,) in db.query(MlPaymentCharge.name).filter(MlPaymentCharge.type == "tax").distinct()
        if is_seller_charge("tax", name) and withholding_kind(name) is not None
    }
    versiones = db.query(ImpuestoTratamientoVenta).order_by(ImpuestoTratamientoVenta.fecha_desde.desc()).all()
    por_nombre: dict = {}
    for version in versiones:
        por_nombre.setdefault(version.charge_name, []).append(version)
    treatment = TaxTreatment.load(db, [])
    hoy = date.today()
    filas = []
    for name in vistos | set(por_nombre):
        por_defecto = is_recoverable_withholding("tax", name)
        configurado = treatment.informativo_on(name, hoy)
        filas.append(
            ImpuestoVentaResponse(
                charge_name=name,
                etiqueta=tax_label(name),
                informativo_por_defecto=por_defecto,
                informativo_hoy=por_defecto if configurado is None else configurado,
                versiones=por_nombre.get(name, []),
            )
        )
    return sorted(filas, key=lambda fila: (fila.etiqueta, fila.charge_name))


@router.post("/impuestos-venta", response_model=ImpuestoVentaCreateResponse)
def crear_impuesto_venta(
    data: ImpuestoVentaCreate,
    db: Session = Depends(get_db),
    # Same edit permission as "% de varios": both are the sale-deduction setup.
    current_user: Usuario = Depends(require_permiso("ml_ops.varios_editar")),
):
    """Crea una versión del tratamiento de un impuesto, cerrando la vigente anterior del mismo impuesto, y
    devuelve cuántas ventas con ese impuesto se van a recalcular."""
    if withholding_kind(data.charge_name) is None or not is_seller_charge("tax", data.charge_name):
        raise HTTPException(status_code=422, detail=f"{data.charge_name} no es una retención de ML")
    existing = (
        db.query(ImpuestoTratamientoVenta)
        .filter(
            ImpuestoTratamientoVenta.charge_name == data.charge_name,
            ImpuestoTratamientoVenta.fecha_desde == data.fecha_desde,
        )
        .first()
    )
    if existing:
        raise HTTPException(
            status_code=400, detail=f"Ya existe una versión de {data.charge_name} para la fecha {data.fecha_desde}"
        )

    abiertas = (
        db.query(ImpuestoTratamientoVenta)
        .filter(
            ImpuestoTratamientoVenta.charge_name == data.charge_name,
            ImpuestoTratamientoVenta.fecha_desde < data.fecha_desde,
            ImpuestoTratamientoVenta.fecha_hasta.is_(None),
        )
        .all()
    )
    for version in abiertas:
        version.fecha_hasta = data.fecha_desde

    # Like "% de varios": the closed windows only shrink to the new start, so the union of old and new windows is
    # "from the earliest touched start forward". The trigger does the re-queueing; this is the count shown.
    afectadas_desde = min([data.fecha_desde] + [version.fecha_desde for version in abiertas])

    nueva = ImpuestoTratamientoVenta(
        charge_name=data.charge_name,
        informativo=data.informativo,
        fecha_desde=data.fecha_desde,
        creado_por=current_user.id,
    )
    db.add(nueva)
    db.commit()
    db.refresh(nueva)

    recalculando = (
        db.query(MlOrdersOps.order_id)
        .join(MlPaymentOps, MlPaymentOps.order_id == MlOrdersOps.order_id)
        .join(MlPaymentCharge, MlPaymentCharge.payment_id == MlPaymentOps.payment_id)
        .filter(MlPaymentCharge.name == data.charge_name, MlOrdersOps.date_created >= afectadas_desde)
        .distinct()
        .count()
    )
    return ImpuestoVentaCreateResponse(mensaje="Versión creada", id=nueva.id, recalculando=recalculando)
