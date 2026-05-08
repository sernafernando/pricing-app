"""
Endpoints para gestión de colectas.

Una colecta agrupa N etiquetas (paquetes) que salen juntas en un mismo retiro.
Identificada por (fecha, numero). Estados: pendiente | despachada.
"""

import logging
from datetime import date, datetime
from typing import List, Optional

from fastapi import APIRouter, Depends, HTTPException, Query
from sqlalchemy.orm import Session
from sqlalchemy import func, and_
from pydantic import BaseModel, ConfigDict, Field

from app.core.database import get_db
from app.api.deps import get_current_user
from app.models.usuario import Usuario
from app.models.colecta import Colecta
from app.models.etiqueta_colecta import EtiquetaColecta
from app.models.mercadolibre_order_shipping import MercadoLibreOrderShipping
from app.models.sale_order_header import SaleOrderHeader
from app.models.sale_order_header_history import SaleOrderHeaderHistory
from app.models.sale_order_status import SaleOrderStatus
from app.services.permisos_service import verificar_permiso
from app.core.sse import sse_publish_bg
from sqlalchemy import desc

router = APIRouter()
logger = logging.getLogger(__name__)


# ── Pydantic models ──────────────────────────────────────────────


class EstadoBreakdownItem(BaseModel):
    """Una entrada de breakdown: nombre del estado, color (si aplica) y count."""

    nombre: str
    color: Optional[str] = None
    cantidad: int

    model_config = ConfigDict(from_attributes=True)


class ColectaResponse(BaseModel):
    """Colecta con conteo de etiquetas y breakdown por estado ERP / ML."""

    id: int
    fecha: date
    numero: int
    estado: str
    despachada_at: Optional[datetime] = None
    observaciones: Optional[str] = None
    total_etiquetas: int = 0
    por_estado_erp: List[EstadoBreakdownItem] = []
    por_estado_ml: List[EstadoBreakdownItem] = []

    model_config = ConfigDict(from_attributes=True)


class ColectaCreateRequest(BaseModel):
    """Crea una colecta. Si numero es None, auto-asigna el siguiente disponible."""

    fecha: date
    numero: Optional[int] = Field(None, ge=1, description="Si se omite, se autoasigna")
    observaciones: Optional[str] = None

    model_config = ConfigDict(from_attributes=True)


class ColectaDespachadaRequest(BaseModel):
    """Marca una colecta como despachada."""

    observaciones: Optional[str] = None

    model_config = ConfigDict(from_attributes=True)


# ── Helpers ──────────────────────────────────────────────────────


def _check_permiso(db: Session, user: Usuario, permiso: str) -> None:
    if not verificar_permiso(db, user, permiso):
        raise HTTPException(status_code=403, detail=f"Sin permiso: {permiso}")


def _siguiente_numero(db: Session, fecha: date) -> int:
    """Retorna el siguiente número de colecta disponible para una fecha."""
    max_num = db.query(func.max(Colecta.numero)).filter(Colecta.fecha == fecha).scalar()
    return (max_num or 0) + 1


def _serializar_con_breakdown(db: Session, colectas: List[Colecta]) -> List[ColectaResponse]:
    """
    Serializa colectas con total_etiquetas + breakdown por estado ERP y ML.

    Estrategia: traer las etiquetas con sus shipping_ids, hacer queries deduplicadas
    a MercadoLibreOrderShipping (ML) y SaleOrderHeader (ERP), agregar facturado por
    SaleOrderHeaderHistory.ct_transaction. Mismo patrón que el listing principal.
    """
    if not colectas:
        return []

    colecta_ids = [c.id for c in colectas]

    etq_rows = (
        db.query(EtiquetaColecta.colecta_id, EtiquetaColecta.shipping_id)
        .filter(EtiquetaColecta.colecta_id.in_(colecta_ids))
        .all()
    )
    if not etq_rows:
        return [
            ColectaResponse(
                id=c.id,
                fecha=c.fecha,
                numero=c.numero,
                estado=c.estado,
                despachada_at=c.despachada_at,
                observaciones=c.observaciones,
                total_etiquetas=0,
                por_estado_erp=[],
                por_estado_ml=[],
            )
            for c in colectas
        ]

    target_ids = list({r.shipping_id for r in etq_rows})

    # ML status dedup
    ranked_ship = (
        db.query(
            MercadoLibreOrderShipping.mlshippingid,
            MercadoLibreOrderShipping.mlstatus,
            func.row_number()
            .over(
                partition_by=MercadoLibreOrderShipping.mlshippingid,
                order_by=desc(MercadoLibreOrderShipping.mlm_id),
            )
            .label("rn"),
        )
        .filter(
            MercadoLibreOrderShipping.mlshippingid.isnot(None),
            MercadoLibreOrderShipping.mlshippingid.in_(target_ids),
        )
        .subquery()
    )
    ml_map = {r.mlshippingid: r.mlstatus for r in db.query(ranked_ship).filter(ranked_ship.c.rn == 1).all()}

    # ERP status dedup (último pedido por shipping)
    ranked_soh = (
        db.query(
            MercadoLibreOrderShipping.mlshippingid,
            SaleOrderHeader.ssos_id,
            func.row_number()
            .over(
                partition_by=MercadoLibreOrderShipping.mlshippingid,
                order_by=desc(SaleOrderHeader.soh_cd),
            )
            .label("rn"),
        )
        .join(SaleOrderHeader, MercadoLibreOrderShipping.mlo_id == SaleOrderHeader.mlo_id)
        .filter(
            MercadoLibreOrderShipping.mlshippingid.isnot(None),
            MercadoLibreOrderShipping.mlo_id.isnot(None),
            SaleOrderHeader.mlo_id.isnot(None),
            MercadoLibreOrderShipping.mlshippingid.in_(target_ids),
        )
        .subquery()
    )
    erp_ssos_map = {r.mlshippingid: r.ssos_id for r in db.query(ranked_soh).filter(ranked_soh.c.rn == 1).all()}

    # Facturado: si hay SaleOrderHeaderHistory con ct_transaction != NULL para ese mlo_id
    ranked_fact = (
        db.query(
            MercadoLibreOrderShipping.mlshippingid,
            func.row_number()
            .over(
                partition_by=MercadoLibreOrderShipping.mlshippingid,
                order_by=desc(SaleOrderHeaderHistory.sohh_cd),
            )
            .label("rn"),
        )
        .join(SaleOrderHeaderHistory, MercadoLibreOrderShipping.mlo_id == SaleOrderHeaderHistory.mlo_id)
        .filter(
            MercadoLibreOrderShipping.mlshippingid.isnot(None),
            MercadoLibreOrderShipping.mlo_id.isnot(None),
            SaleOrderHeaderHistory.ct_transaction.isnot(None),
            MercadoLibreOrderShipping.mlshippingid.in_(target_ids),
        )
        .subquery()
    )
    facturado_ids = {r.mlshippingid for r in db.query(ranked_fact.c.mlshippingid).filter(ranked_fact.c.rn == 1).all()}

    # Nombres y colores ERP
    ssos_ids = {v for v in erp_ssos_map.values() if v}
    status_map = {}
    if ssos_ids:
        status_map = {
            s.ssos_id: s for s in db.query(SaleOrderStatus).filter(SaleOrderStatus.ssos_id.in_(ssos_ids)).all()
        }

    # Agrupar por colecta_id
    breakdown_by_colecta: dict[int, dict] = {cid: {"total": 0, "erp": {}, "ml": {}} for cid in colecta_ids}
    for row in etq_rows:
        b = breakdown_by_colecta[row.colecta_id]
        b["total"] += 1

        sid = row.shipping_id
        erp_ssos_id = erp_ssos_map.get(sid)
        erp_status = status_map.get(erp_ssos_id) if erp_ssos_id else None
        is_facturado = sid in facturado_ids

        if erp_status:
            key = (erp_status.ssos_name, erp_status.ssos_color)
        elif is_facturado:
            key = ("Facturado", "#22c55e")
        else:
            key = None

        if key is not None:
            b["erp"][key] = b["erp"].get(key, 0) + 1

        ml_status = ml_map.get(sid)
        if ml_status:
            b["ml"][ml_status] = b["ml"].get(ml_status, 0) + 1

    return [
        ColectaResponse(
            id=c.id,
            fecha=c.fecha,
            numero=c.numero,
            estado=c.estado,
            despachada_at=c.despachada_at,
            observaciones=c.observaciones,
            total_etiquetas=breakdown_by_colecta[c.id]["total"],
            por_estado_erp=[
                EstadoBreakdownItem(nombre=name, color=color, cantidad=cnt)
                for (name, color), cnt in sorted(breakdown_by_colecta[c.id]["erp"].items(), key=lambda kv: -kv[1])
            ],
            por_estado_ml=[
                EstadoBreakdownItem(nombre=name, cantidad=cnt)
                for name, cnt in sorted(breakdown_by_colecta[c.id]["ml"].items(), key=lambda kv: -kv[1])
            ],
        )
        for c in colectas
    ]


# ── Endpoints ────────────────────────────────────────────────────


@router.get(
    "/colectas",
    response_model=List[ColectaResponse],
    summary="Listar colectas",
)
def listar_colectas(
    fecha_desde: Optional[date] = Query(None),
    fecha_hasta: Optional[date] = Query(None),
    estado: Optional[str] = Query(None, description="pendiente | despachada"),
    incluir_despachadas: bool = Query(True, description="Si False, oculta las despachadas"),
    db: Session = Depends(get_db),
    current_user: Usuario = Depends(get_current_user),
) -> List[ColectaResponse]:
    """Lista colectas con filtros y conteo de etiquetas vinculadas."""
    _check_permiso(db, current_user, "envios_flex.ver")

    q = db.query(Colecta)

    if fecha_desde:
        q = q.filter(Colecta.fecha >= fecha_desde)
    if fecha_hasta:
        q = q.filter(Colecta.fecha <= fecha_hasta)
    if estado:
        q = q.filter(Colecta.estado == estado)
    elif not incluir_despachadas:
        q = q.filter(Colecta.estado == Colecta.ESTADO_PENDIENTE)

    colectas = q.order_by(Colecta.fecha.desc(), Colecta.numero.asc()).all()
    return _serializar_con_breakdown(db, colectas)


@router.get(
    "/colectas/siguiente-numero",
    response_model=dict,
    summary="Siguiente número de colecta para una fecha",
)
def siguiente_numero_colecta(
    fecha: date = Query(...),
    db: Session = Depends(get_db),
    current_user: Usuario = Depends(get_current_user),
) -> dict:
    """Devuelve el siguiente número disponible para una fecha dada."""
    _check_permiso(db, current_user, "envios_flex.ver")
    return {"fecha": fecha.isoformat(), "siguiente": _siguiente_numero(db, fecha)}


@router.post(
    "/colectas",
    response_model=ColectaResponse,
    summary="Crear colecta",
)
def crear_colecta(
    payload: ColectaCreateRequest,
    db: Session = Depends(get_db),
    current_user: Usuario = Depends(get_current_user),
) -> ColectaResponse:
    """
    Crea una colecta nueva. Si numero es None, auto-asigna el siguiente disponible
    para la fecha dada.
    """
    _check_permiso(db, current_user, "envios_flex.subir_etiquetas")

    numero = payload.numero or _siguiente_numero(db, payload.fecha)

    existente = db.query(Colecta).filter(and_(Colecta.fecha == payload.fecha, Colecta.numero == numero)).first()
    if existente:
        raise HTTPException(409, f"Ya existe colecta {payload.fecha} #{numero}")

    colecta = Colecta(
        fecha=payload.fecha,
        numero=numero,
        estado=Colecta.ESTADO_PENDIENTE,
        observaciones=payload.observaciones,
    )
    db.add(colecta)
    db.commit()
    db.refresh(colecta)

    sse_publish_bg("colectas:changed", {"hint": "reload"})

    return _serializar_con_breakdown(db, [colecta])[0]


@router.patch(
    "/colectas/{colecta_id}/despachar",
    response_model=ColectaResponse,
    summary="Marcar colecta como despachada",
)
def despachar_colecta(
    colecta_id: int,
    payload: ColectaDespachadaRequest,
    db: Session = Depends(get_db),
    current_user: Usuario = Depends(get_current_user),
) -> ColectaResponse:
    """Marca una colecta como despachada (ya se fue)."""
    _check_permiso(db, current_user, "envios_flex.subir_etiquetas")

    colecta = db.query(Colecta).filter(Colecta.id == colecta_id).first()
    if not colecta:
        raise HTTPException(404, "Colecta no encontrada")

    if colecta.estado == Colecta.ESTADO_DESPACHADA:
        raise HTTPException(400, "La colecta ya está despachada")

    colecta.estado = Colecta.ESTADO_DESPACHADA
    colecta.despachada_at = datetime.utcnow()
    if payload.observaciones is not None:
        colecta.observaciones = payload.observaciones

    db.commit()
    db.refresh(colecta)

    sse_publish_bg("colectas:changed", {"hint": "reload"})

    return _serializar_con_breakdown(db, [colecta])[0]


@router.patch(
    "/colectas/{colecta_id}/reabrir",
    response_model=ColectaResponse,
    summary="Reabrir colecta despachada",
)
def reabrir_colecta(
    colecta_id: int,
    db: Session = Depends(get_db),
    current_user: Usuario = Depends(get_current_user),
) -> ColectaResponse:
    """Vuelve una colecta despachada al estado pendiente (por si se despachó por error)."""
    _check_permiso(db, current_user, "envios_flex.subir_etiquetas")

    colecta = db.query(Colecta).filter(Colecta.id == colecta_id).first()
    if not colecta:
        raise HTTPException(404, "Colecta no encontrada")

    if colecta.estado == Colecta.ESTADO_PENDIENTE:
        raise HTTPException(400, "La colecta ya está pendiente")

    colecta.estado = Colecta.ESTADO_PENDIENTE
    colecta.despachada_at = None

    db.commit()
    db.refresh(colecta)

    sse_publish_bg("colectas:changed", {"hint": "reload"})

    return _serializar_con_breakdown(db, [colecta])[0]


@router.delete(
    "/colectas/{colecta_id}",
    response_model=dict,
    summary="Borrar colecta",
)
def borrar_colecta(
    colecta_id: int,
    db: Session = Depends(get_db),
    current_user: Usuario = Depends(get_current_user),
) -> dict:
    """
    Borra una colecta. Solo se permite si NO tiene etiquetas asociadas (para evitar
    pérdida accidental). Si querés borrar con etiquetas, primero borralas.
    """
    _check_permiso(db, current_user, "envios_flex.eliminar")

    colecta = db.query(Colecta).filter(Colecta.id == colecta_id).first()
    if not colecta:
        raise HTTPException(404, "Colecta no encontrada")

    total = (db.query(func.count(EtiquetaColecta.id)).filter(EtiquetaColecta.colecta_id == colecta_id).scalar()) or 0

    if total > 0:
        raise HTTPException(
            400,
            f"La colecta tiene {total} etiqueta(s). Borralas primero.",
        )

    db.delete(colecta)
    db.commit()

    sse_publish_bg("colectas:changed", {"hint": "reload"})

    return {"ok": True, "id": colecta_id}
