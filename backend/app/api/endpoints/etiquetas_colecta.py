"""
Endpoints para gestión de etiquetas de colecta (checkeo).

Permite:
- Subir archivos .zip/.txt con etiquetas ZPL de colecta
- Listar etiquetas con estados ERP y ML (solo lectura)
- Estadísticas totales y por día

Los archivos ZPL contienen JSONs embebidos en los QR codes con formato:
{"id":"46458064834","sender_id":413658225,"hash_code":"...","security_digit":"0"}

El campo "id" del QR = mlshippingid en tb_mercadolibre_orders_shipping.
"""

import logging
import re
import json
import zipfile
from io import BytesIO
from datetime import date

from fastapi import APIRouter, Depends, HTTPException, UploadFile, File, Query
from sqlalchemy.orm import Session, aliased
from sqlalchemy import func, and_, desc
from typing import List, Optional
from pydantic import BaseModel, ConfigDict, Field

from app.core.database import get_db
from app.api.deps import get_current_user
from app.models.usuario import Usuario
from app.models.etiqueta_colecta import EtiquetaColecta
from app.models.mercadolibre_order_shipping import MercadoLibreOrderShipping
from app.models.sale_order_header import SaleOrderHeader
from app.models.sale_order_status import SaleOrderStatus
from app.services.permisos_service import verificar_permiso

router = APIRouter()

QR_JSON_REGEX = re.compile(r'\{"id":"[^}]+\}')

logger = logging.getLogger(__name__)


# ── Pydantic models ──────────────────────────────────────────────


class UploadResultResponse(BaseModel):
    """Resultado de un upload de archivo ZPL."""

    total: int
    nuevas: int
    duplicadas: int
    errores: int = 0
    detalle_errores: List[str] = []

    model_config = ConfigDict(from_attributes=True)


class EtiquetaColectaResponse(BaseModel):
    """Respuesta para una etiqueta de colecta con estados."""

    shipping_id: str
    fecha_carga: date
    mlreceiver_name: Optional[str] = None
    mlstatus: Optional[str] = None
    ml_order_id: Optional[str] = None
    ssos_id: Optional[int] = None
    ssos_name: Optional[str] = None
    ssos_color: Optional[str] = None

    model_config = ConfigDict(from_attributes=True)


class EstadisticasColectaResponse(BaseModel):
    """Estadísticas de etiquetas de colecta."""

    total: int
    por_estado_ml: dict[str, int] = {}
    por_estado_erp: dict[str, int] = {}

    model_config = ConfigDict(from_attributes=True)


class EstadisticaDiaColectaItem(BaseModel):
    """Estadísticas de un día de colecta."""

    fecha: date
    total: int = 0
    flex: int = 0
    manuales: int = 0
    por_cordon: dict[str, int] = {}
    sin_cordon: int = 0
    con_logistica: int = 0
    sin_logistica: int = 0

    model_config = ConfigDict(from_attributes=True)


class EstadisticasPorDiaColectaResponse(BaseModel):
    """Respuesta de estadísticas por día."""

    dias: List[EstadisticaDiaColectaItem]

    model_config = ConfigDict(from_attributes=True)


class ScanIndividualRequest(BaseModel):
    """Payload para carga individual por escaneo de QR."""

    qr_json: str = Field(..., description="JSON crudo del QR de la etiqueta (tal cual lo lee la pistola)")

    model_config = ConfigDict(from_attributes=True)


class ScanIndividualResponse(BaseModel):
    """Resultado de carga individual por escaneo."""

    shipping_id: str
    nueva: bool
    mensaje: str

    model_config = ConfigDict(from_attributes=True)


class BorrarColectaRequest(BaseModel):
    """Payload para borrar etiquetas de colecta."""

    shipping_ids: List[str] = Field(min_length=1)

    model_config = ConfigDict(from_attributes=True)


# ── Helpers ──────────────────────────────────────────────────────


def _check_permiso(db: Session, user: Usuario, permiso: str) -> None:
    """Verifica un permiso o lanza 403."""
    if not verificar_permiso(db, user, permiso):
        raise HTTPException(status_code=403, detail=f"Sin permiso: {permiso}")


def _extraer_qrs_de_texto(text: str) -> List[str]:
    """Extrae todos los JSONs de QR de un texto ZPL."""
    return QR_JSON_REGEX.findall(text)


def _parse_qr_json(raw: str) -> dict:
    """Parsea un JSON de QR y extrae shipping_id, sender_id, hash_code."""
    data = json.loads(raw)
    shipping_id = data.get("id")
    if not shipping_id:
        raise ValueError("JSON del QR no tiene campo 'id'")
    return {
        "shipping_id": str(shipping_id),
        "sender_id": data.get("sender_id"),
        "hash_code": data.get("hash_code"),
    }


def _insertar_etiqueta_colecta(
    db: Session,
    shipping_id: str,
    sender_id: Optional[int],
    hash_code: Optional[str],
    nombre_archivo: Optional[str],
    fecha_carga: date,
) -> bool:
    """
    Inserta una etiqueta de colecta si no existe.
    Retorna True si se insertó (nueva), False si ya existía (duplicada).
    """
    existente = db.query(EtiquetaColecta).filter(EtiquetaColecta.shipping_id == shipping_id).first()
    if existente:
        return False

    etiqueta = EtiquetaColecta(
        shipping_id=shipping_id,
        sender_id=sender_id,
        hash_code=hash_code,
        nombre_archivo=nombre_archivo,
        fecha_carga=fecha_carga,
    )
    db.add(etiqueta)
    return True


def _soh_status_subquery(db: Session):
    """
    Subquery deduplicada: estado ERP por shipping_id.

    Cruza orders_shipping (por mlshippingid) → sale_order_header (por mlo_id).
    Toma el pedido más reciente (mayor soh_cd) con ROW_NUMBER.
    """
    ranked = (
        db.query(
            MercadoLibreOrderShipping.mlshippingid.label("shipping_id_str"),
            SaleOrderHeader.ssos_id.label("soh_ssos_id"),
            func.row_number()
            .over(
                partition_by=MercadoLibreOrderShipping.mlshippingid,
                order_by=desc(SaleOrderHeader.soh_cd),
            )
            .label("rn"),
        )
        .join(
            SaleOrderHeader,
            MercadoLibreOrderShipping.mlo_id == SaleOrderHeader.mlo_id,
        )
        .filter(
            MercadoLibreOrderShipping.mlshippingid.isnot(None),
            MercadoLibreOrderShipping.mlo_id.isnot(None),
            SaleOrderHeader.mlo_id.isnot(None),
        )
        .subquery()
    )

    return (
        db.query(
            ranked.c.shipping_id_str,
            ranked.c.soh_ssos_id,
        )
        .filter(ranked.c.rn == 1)
        .subquery()
    )


def _shipping_dedup_subquery(db: Session):
    """
    Subquery deduplicada: una fila por mlshippingid de MercadoLibreOrderShipping.

    Toma la fila más reciente (mayor mlm_id) con ROW_NUMBER.
    Solo extrae los campos necesarios para colecta: receiver_name, mlstatus, mlo_id.
    """
    ranked = (
        db.query(
            MercadoLibreOrderShipping.mlshippingid.label("mlshippingid"),
            MercadoLibreOrderShipping.mlo_id,
            MercadoLibreOrderShipping.mlreceiver_name,
            MercadoLibreOrderShipping.mlstatus,
            func.row_number()
            .over(
                partition_by=MercadoLibreOrderShipping.mlshippingid,
                order_by=desc(MercadoLibreOrderShipping.mlm_id),
            )
            .label("rn"),
        )
        .filter(MercadoLibreOrderShipping.mlshippingid.isnot(None))
        .subquery()
    )

    return (
        db.query(
            ranked.c.mlshippingid,
            ranked.c.mlo_id,
            ranked.c.mlreceiver_name,
            ranked.c.mlstatus,
        )
        .filter(ranked.c.rn == 1)
        .subquery()
    )


# ── Endpoints ────────────────────────────────────────────────────


@router.post(
    "/etiquetas-colecta/upload",
    response_model=UploadResultResponse,
    summary="Subir archivo ZPL de colecta",
)
async def upload_etiquetas_colecta(
    file: UploadFile = File(..., description="Archivo .zip o .txt con etiquetas ZPL de colecta"),
    db: Session = Depends(get_db),
    current_user: Usuario = Depends(get_current_user),
) -> UploadResultResponse:
    """
    Sube un archivo ZPL de colecta (.zip o .txt), extrae los QR codes
    y registra las etiquetas en la tabla etiquetas_colecta.
    """
    _check_permiso(db, current_user, "envios_flex.subir_etiquetas")

    filename = file.filename or ""
    if not filename.endswith((".zip", ".txt")):
        raise HTTPException(400, "Solo se aceptan archivos .zip o .txt")

    content = await file.read()

    # Extraer texto del archivo
    if filename.endswith(".zip"):
        try:
            with zipfile.ZipFile(BytesIO(content)) as zf:
                txt_files = [n for n in zf.namelist() if n.endswith(".txt") and "__MACOSX" not in n]
                if not txt_files:
                    raise HTTPException(400, "El ZIP no contiene archivos .txt")
                text_content = zf.read(txt_files[0]).decode("utf-8")
        except zipfile.BadZipFile:
            raise HTTPException(400, "Archivo ZIP corrupto")
    else:
        text_content = content.decode("utf-8")

    # Extraer QR JSONs
    qr_jsons = _extraer_qrs_de_texto(text_content)
    if not qr_jsons:
        raise HTTPException(400, "No se encontraron QR codes en el archivo")

    total = len(qr_jsons)
    nuevas = 0
    duplicadas = 0
    errores = 0
    detalle_errores: List[str] = []
    hoy = date.today()

    for raw_json in qr_jsons:
        try:
            parsed = _parse_qr_json(raw_json)
            insertada = _insertar_etiqueta_colecta(
                db,
                shipping_id=parsed["shipping_id"],
                sender_id=parsed["sender_id"],
                hash_code=parsed["hash_code"],
                nombre_archivo=filename,
                fecha_carga=hoy,
            )
            if insertada:
                nuevas += 1
            else:
                duplicadas += 1
        except Exception as e:
            errores += 1
            if len(detalle_errores) < 20:
                detalle_errores.append(str(e))

    try:
        db.commit()
    except Exception as e:
        db.rollback()
        logger.error("Error en commit de upload colecta: %s", e)
        raise HTTPException(500, "Error guardando etiquetas")

    return UploadResultResponse(
        total=total,
        nuevas=nuevas,
        duplicadas=duplicadas,
        errores=errores,
        detalle_errores=detalle_errores,
    )


@router.get(
    "/etiquetas-colecta",
    response_model=List[EtiquetaColectaResponse],
    summary="Listar etiquetas de colecta con estados",
)
def listar_etiquetas_colecta(
    fecha_desde: Optional[date] = Query(None, description="Filtrar desde fecha (inclusive)"),
    fecha_hasta: Optional[date] = Query(None, description="Filtrar hasta fecha (inclusive)"),
    mlstatus: Optional[str] = Query(None, description="Filtrar por estado ML"),
    ssos_id: Optional[int] = Query(None, description="Filtrar por estado ERP (ssos_id)"),
    search: Optional[str] = Query(None, description="Buscar por shipping_id o destinatario"),
    db: Session = Depends(get_db),
    current_user: Usuario = Depends(get_current_user),
) -> List[EtiquetaColectaResponse]:
    """
    Lista etiquetas de colecta con JOINs a:
    - tb_mercadolibre_orders_shipping (estado ML, destinatario)
    - tb_sale_order_header + tb_sale_order_status (estado ERP)
    """
    _check_permiso(db, current_user, "envios_flex.ver")

    soh_sub = _soh_status_subquery(db)
    shipping_sub = _shipping_dedup_subquery(db)

    from app.models.mercadolibre_order_header import MercadoLibreOrderHeader

    # Subquery para ml_order_id
    mlo_sub = (
        db.query(
            MercadoLibreOrderHeader.mlo_id,
            MercadoLibreOrderHeader.mlorder_id,
        )
        .distinct(MercadoLibreOrderHeader.mlo_id)
        .subquery()
    )

    query = (
        db.query(
            EtiquetaColecta.shipping_id,
            EtiquetaColecta.fecha_carga,
            shipping_sub.c.mlreceiver_name,
            shipping_sub.c.mlstatus,
            soh_sub.c.soh_ssos_id.label("ssos_id"),
            SaleOrderStatus.ssos_name,
            SaleOrderStatus.ssos_color,
            mlo_sub.c.mlorder_id.label("ml_order_id"),
        )
        .outerjoin(
            shipping_sub,
            EtiquetaColecta.shipping_id == shipping_sub.c.mlshippingid,
        )
        .outerjoin(
            soh_sub,
            EtiquetaColecta.shipping_id == soh_sub.c.shipping_id_str,
        )
        .outerjoin(
            SaleOrderStatus,
            soh_sub.c.soh_ssos_id == SaleOrderStatus.ssos_id,
        )
        .outerjoin(
            mlo_sub,
            shipping_sub.c.mlo_id == mlo_sub.c.mlo_id,
        )
    )

    # Filtros
    if fecha_desde:
        query = query.filter(EtiquetaColecta.fecha_carga >= fecha_desde)
    if fecha_hasta:
        query = query.filter(EtiquetaColecta.fecha_carga <= fecha_hasta)
    if mlstatus:
        query = query.filter(shipping_sub.c.mlstatus == mlstatus)
    if ssos_id is not None:
        query = query.filter(soh_sub.c.soh_ssos_id == ssos_id)
    if search:
        search_like = f"%{search}%"
        query = query.filter(
            EtiquetaColecta.shipping_id.ilike(search_like) | shipping_sub.c.mlreceiver_name.ilike(search_like)
        )

    query = query.order_by(EtiquetaColecta.shipping_id)

    results = query.all()

    return [
        EtiquetaColectaResponse(
            shipping_id=row.shipping_id,
            fecha_carga=row.fecha_carga,
            mlreceiver_name=row.mlreceiver_name,
            mlstatus=row.mlstatus,
            ml_order_id=row.ml_order_id,
            ssos_id=row.ssos_id,
            ssos_name=row.ssos_name,
            ssos_color=row.ssos_color,
        )
        for row in results
    ]


@router.get(
    "/etiquetas-colecta/estadisticas",
    response_model=EstadisticasColectaResponse,
    summary="Estadísticas de etiquetas de colecta",
)
def estadisticas_colecta(
    fecha_desde: Optional[date] = Query(None),
    fecha_hasta: Optional[date] = Query(None),
    mlstatus: Optional[str] = Query(None),
    ssos_id: Optional[int] = Query(None),
    search: Optional[str] = Query(None),
    db: Session = Depends(get_db),
    current_user: Usuario = Depends(get_current_user),
) -> EstadisticasColectaResponse:
    """Estadísticas totales de etiquetas de colecta."""
    _check_permiso(db, current_user, "envios_flex.ver")

    shipping_sub = _shipping_dedup_subquery(db)
    soh_sub = _soh_status_subquery(db)

    # Base query: IDs filtrados
    base = (
        db.query(EtiquetaColecta.id, EtiquetaColecta.shipping_id)
        .outerjoin(
            shipping_sub,
            EtiquetaColecta.shipping_id == shipping_sub.c.mlshippingid,
        )
        .outerjoin(
            soh_sub,
            EtiquetaColecta.shipping_id == soh_sub.c.shipping_id_str,
        )
    )

    if fecha_desde:
        base = base.filter(EtiquetaColecta.fecha_carga >= fecha_desde)
    if fecha_hasta:
        base = base.filter(EtiquetaColecta.fecha_carga <= fecha_hasta)
    if mlstatus:
        base = base.filter(shipping_sub.c.mlstatus == mlstatus)
    if ssos_id is not None:
        base = base.filter(soh_sub.c.soh_ssos_id == ssos_id)
    if search:
        search_like = f"%{search}%"
        base = base.filter(
            EtiquetaColecta.shipping_id.ilike(search_like) | shipping_sub.c.mlreceiver_name.ilike(search_like)
        )

    filtered_ids_sub = base.subquery()
    total = db.query(func.count(filtered_ids_sub.c.id)).scalar() or 0

    # Por estado ML
    ml_rows = (
        db.query(
            shipping_sub.c.mlstatus,
            func.count().label("cantidad"),
        )
        .join(
            filtered_ids_sub,
            filtered_ids_sub.c.shipping_id == shipping_sub.c.mlshippingid,
        )
        .filter(shipping_sub.c.mlstatus.isnot(None))
        .group_by(shipping_sub.c.mlstatus)
        .all()
    )
    por_estado_ml = {row.mlstatus: row.cantidad for row in ml_rows}

    # Por estado ERP
    erp_rows = (
        db.query(
            SaleOrderStatus.ssos_name,
            func.count().label("cantidad"),
        )
        .join(soh_sub, soh_sub.c.soh_ssos_id == SaleOrderStatus.ssos_id)
        .join(
            filtered_ids_sub,
            filtered_ids_sub.c.shipping_id == soh_sub.c.shipping_id_str,
        )
        .group_by(SaleOrderStatus.ssos_name)
        .all()
    )
    por_estado_erp = {row.ssos_name: row.cantidad for row in erp_rows}

    return EstadisticasColectaResponse(
        total=total,
        por_estado_ml=por_estado_ml,
        por_estado_erp=por_estado_erp,
    )


@router.get(
    "/etiquetas-colecta/estadisticas-por-dia",
    response_model=EstadisticasPorDiaColectaResponse,
    summary="Estadísticas de colecta por día",
)
def estadisticas_por_dia_colecta(
    fecha_desde: date = Query(..., description="Fecha desde (inclusive)"),
    fecha_hasta: date = Query(..., description="Fecha hasta (inclusive)"),
    db: Session = Depends(get_db),
    current_user: Usuario = Depends(get_current_user),
) -> EstadisticasPorDiaColectaResponse:
    """Recuento de etiquetas de colecta por día."""
    _check_permiso(db, current_user, "envios_flex.ver")

    rows = (
        db.query(
            EtiquetaColecta.fecha_carga,
            func.count().label("total"),
        )
        .filter(
            EtiquetaColecta.fecha_carga >= fecha_desde,
            EtiquetaColecta.fecha_carga <= fecha_hasta,
        )
        .group_by(EtiquetaColecta.fecha_carga)
        .order_by(EtiquetaColecta.fecha_carga)
        .all()
    )

    dias = [
        EstadisticaDiaColectaItem(
            fecha=row.fecha_carga,
            total=row.total,
            flex=row.total,
            manuales=0,
        )
        for row in rows
    ]

    return EstadisticasPorDiaColectaResponse(dias=dias)


@router.post(
    "/etiquetas-colecta/scan",
    response_model=ScanIndividualResponse,
    summary="Carga individual por escaneo de QR",
)
def scan_individual_colecta(
    payload: ScanIndividualRequest,
    db: Session = Depends(get_db),
    current_user: Usuario = Depends(get_current_user),
) -> ScanIndividualResponse:
    """
    Recibe el JSON crudo del QR (escaneado con pistola) y registra
    la etiqueta de colecta si no existe.
    """
    _check_permiso(db, current_user, "envios_flex.subir_etiquetas")

    try:
        parsed = _parse_qr_json(payload.qr_json)
    except (json.JSONDecodeError, ValueError) as e:
        raise HTTPException(400, f"QR inválido: {e}")

    hoy = date.today()
    insertada = _insertar_etiqueta_colecta(
        db,
        shipping_id=parsed["shipping_id"],
        sender_id=parsed["sender_id"],
        hash_code=parsed["hash_code"],
        nombre_archivo="scan_individual",
        fecha_carga=hoy,
    )

    try:
        db.commit()
    except Exception as e:
        db.rollback()
        logger.error("Error en commit de scan individual colecta: %s", e)
        raise HTTPException(500, "Error guardando etiqueta")

    if insertada:
        return ScanIndividualResponse(
            shipping_id=parsed["shipping_id"],
            nueva=True,
            mensaje=f"Etiqueta {parsed['shipping_id']} cargada",
        )
    return ScanIndividualResponse(
        shipping_id=parsed["shipping_id"],
        nueva=False,
        mensaje=f"Etiqueta {parsed['shipping_id']} ya existía",
    )


@router.delete(
    "/etiquetas-colecta",
    response_model=dict,
    summary="Borrar etiquetas de colecta",
)
def borrar_etiquetas_colecta(
    payload: BorrarColectaRequest,
    db: Session = Depends(get_db),
    current_user: Usuario = Depends(get_current_user),
) -> dict:
    """Elimina etiquetas de colecta por shipping_id."""
    _check_permiso(db, current_user, "envios_flex.eliminar")

    etiquetas = db.query(EtiquetaColecta).filter(EtiquetaColecta.shipping_id.in_(payload.shipping_ids)).all()

    if not etiquetas:
        raise HTTPException(404, "No se encontraron etiquetas para borrar")

    deleted = (
        db.query(EtiquetaColecta)
        .filter(EtiquetaColecta.shipping_id.in_(payload.shipping_ids))
        .delete(synchronize_session="fetch")
    )

    db.commit()

    return {"ok": True, "eliminadas": deleted}
