"""
Endpoints para gestión de etiquetas de colecta (checkeo).

Permite:
- Subir archivos .zip/.txt con etiquetas ZPL de colecta
- Listar etiquetas con estados ERP y ML (solo lectura)
- Estadísticas totales y por día

Los archivos ZPL contienen JSONs embebidos en los QR codes con formatos:
{"id":"46458064834","t":"lm"}
{"carrier_data":"HE023919525|Domicilio|3460|","id":"46585811359","t":"lm"}

El campo "id" del QR = mlshippingid en tb_mercadolibre_orders_shipping.
Nota: "id" puede NO ser el primer campo del JSON (ej: carrier_data va primero).
"""

import logging
import re
import json
import zipfile
from io import BytesIO
from datetime import date

from fastapi import APIRouter, Depends, HTTPException, UploadFile, File, Query
from sqlalchemy.orm import Session
from sqlalchemy import func, desc
from typing import List, Optional
from pydantic import BaseModel, ConfigDict, Field

from app.core.database import get_db
from app.api.deps import get_current_user
from app.models.usuario import Usuario
from app.models.etiqueta_colecta import EtiquetaColecta
from app.models.mercadolibre_order_shipping import MercadoLibreOrderShipping
from app.models.mercadolibre_order_detail import MercadoLibreOrderDetail
from app.models.tb_item import TBItem
from app.models.sale_order_header import SaleOrderHeader
from app.models.sale_order_status import SaleOrderStatus
from app.services.permisos_service import verificar_permiso
from app.core.sse import sse_publish, sse_publish_bg

router = APIRouter()

QR_JSON_REGEX = re.compile(r'\{[^}]*"id":"[^}]+\}')

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
    por_estado_erp: dict[str, int] = {}
    por_estado_ml: dict[str, int] = {}

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


class ItemEnvioColectaResponse(BaseModel):
    """Item/producto de un envío de colecta."""

    item_id: Optional[int] = None
    item_code: Optional[str] = None
    descripcion: str
    cantidad: float
    precio_unitario: Optional[float] = None

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


def _procesar_archivo_zpl(
    content: bytes,
    filename: str,
    db: Session,
    fecha_carga: date,
) -> tuple[int, int, int, int, List[str]]:
    """
    Procesa un archivo ZPL (.zip o .txt), extrae QRs y registra etiquetas.

    Retorna (total, nuevas, duplicadas, errores, detalle_errores).
    No hace commit — el caller decide cuándo commitear.
    """
    if filename.endswith(".zip"):
        try:
            with zipfile.ZipFile(BytesIO(content)) as zf:
                txt_files = [n for n in zf.namelist() if n.endswith(".txt") and "__MACOSX" not in n]
                if not txt_files:
                    return 0, 0, 0, 1, [f"{filename}: el ZIP no contiene archivos .txt"]
                text_content = zf.read(txt_files[0]).decode("utf-8")
        except zipfile.BadZipFile:
            return 0, 0, 0, 1, [f"{filename}: archivo ZIP corrupto"]
    else:
        text_content = content.decode("utf-8")

    qr_jsons = _extraer_qrs_de_texto(text_content)
    if not qr_jsons:
        return 0, 0, 0, 1, [f"{filename}: no se encontraron QR codes"]

    total = len(qr_jsons)
    nuevas = 0
    duplicadas = 0
    errores = 0
    detalle_errores: List[str] = []

    for raw_json in qr_jsons:
        try:
            parsed = _parse_qr_json(raw_json)
            insertada = _insertar_etiqueta_colecta(
                db,
                shipping_id=parsed["shipping_id"],
                sender_id=parsed["sender_id"],
                hash_code=parsed["hash_code"],
                nombre_archivo=filename,
                fecha_carga=fecha_carga,
            )
            if insertada:
                nuevas += 1
            else:
                duplicadas += 1
        except Exception as e:
            errores += 1
            if len(detalle_errores) < 20:
                detalle_errores.append(f"{filename}: {e}")

    return total, nuevas, duplicadas, errores, detalle_errores


@router.post(
    "/etiquetas-colecta/upload",
    response_model=UploadResultResponse,
    summary="Subir archivos ZPL de colecta",
)
async def upload_etiquetas_colecta(
    files: List[UploadFile] = File(..., description="Archivos .zip o .txt con etiquetas ZPL de colecta"),
    db: Session = Depends(get_db),
    current_user: Usuario = Depends(get_current_user),
) -> UploadResultResponse:
    """
    Sube uno o más archivos ZPL de colecta (.zip o .txt), extrae los QR codes
    y registra las etiquetas en la tabla etiquetas_colecta.
    """
    _check_permiso(db, current_user, "envios_flex.subir_etiquetas")

    total = 0
    nuevas = 0
    duplicadas = 0
    errores = 0
    detalle_errores: List[str] = []
    hoy = date.today()

    for file in files:
        filename = file.filename or ""
        if not filename.endswith((".zip", ".txt")):
            errores += 1
            detalle_errores.append(f"{filename}: solo se aceptan .zip o .txt")
            continue

        content = await file.read()
        f_total, f_nuevas, f_dup, f_err, f_det = _procesar_archivo_zpl(content, filename, db, hoy)
        total += f_total
        nuevas += f_nuevas
        duplicadas += f_dup
        errores += f_err
        detalle_errores.extend(f_det)

    if total == 0 and errores == 0:
        raise HTTPException(400, "No se encontraron etiquetas en los archivos")

    try:
        db.commit()
    except Exception as e:
        db.rollback()
        logger.error("Error en commit de upload colecta: %s", e)
        raise HTTPException(500, "Error guardando etiquetas")

    await sse_publish("etiquetas:changed", {"hint": "reload"})

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

    Optimización: primero filtra los shipping_ids por fecha en etiquetas_colecta,
    luego hace subqueries de dedup acotadas solo a esos IDs (evita escanear
    tablas completas de orders_shipping y sale_order_header).
    """
    _check_permiso(db, current_user, "envios_flex.ver")

    # 1) Pre-filtrar shipping_ids de colecta por fecha (query muy rápida sobre tabla pequeña)
    ids_query = db.query(EtiquetaColecta.shipping_id)
    if fecha_desde:
        ids_query = ids_query.filter(EtiquetaColecta.fecha_carga >= fecha_desde)
    if fecha_hasta:
        ids_query = ids_query.filter(EtiquetaColecta.fecha_carga <= fecha_hasta)
    target_ids_sub = ids_query.subquery()

    # 2) Subquery dedup de shipping ACOTADA a los IDs que necesitamos
    ranked_ship = (
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
        .filter(
            MercadoLibreOrderShipping.mlshippingid.isnot(None),
            MercadoLibreOrderShipping.mlshippingid.in_(db.query(target_ids_sub.c.shipping_id)),
        )
        .subquery()
    )
    shipping_sub = (
        db.query(
            ranked_ship.c.mlshippingid,
            ranked_ship.c.mlo_id,
            ranked_ship.c.mlreceiver_name,
            ranked_ship.c.mlstatus,
        )
        .filter(ranked_ship.c.rn == 1)
        .subquery()
    )

    # 3) Subquery dedup de estado ERP ACOTADA a los IDs que necesitamos
    ranked_soh = (
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
            MercadoLibreOrderShipping.mlshippingid.in_(db.query(target_ids_sub.c.shipping_id)),
        )
        .subquery()
    )
    soh_sub = (
        db.query(
            ranked_soh.c.shipping_id_str,
            ranked_soh.c.soh_ssos_id,
        )
        .filter(ranked_soh.c.rn == 1)
        .subquery()
    )

    from app.models.mercadolibre_order_header import MercadoLibreOrderHeader

    # 4) Subquery para ml_order_id (solo los mlo_ids relevantes)
    mlo_sub = (
        db.query(
            MercadoLibreOrderHeader.mlo_id,
            MercadoLibreOrderHeader.mlorder_id,
        )
        .distinct(MercadoLibreOrderHeader.mlo_id)
        .subquery()
    )

    # 5) Query principal con JOINs a subqueries acotadas
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

    # 6) Filtros sobre query principal
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
    """Recuento de etiquetas de colecta por día, con desglose por estado ERP y ML."""
    _check_permiso(db, current_user, "envios_flex.ver")

    shipping_sub = _shipping_dedup_subquery(db)
    soh_sub = _soh_status_subquery(db)

    # Query base con JOINs para obtener estados
    base = (
        db.query(
            EtiquetaColecta.fecha_carga,
            EtiquetaColecta.shipping_id,
            shipping_sub.c.mlstatus,
            SaleOrderStatus.ssos_name,
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
        .filter(
            EtiquetaColecta.fecha_carga >= fecha_desde,
            EtiquetaColecta.fecha_carga <= fecha_hasta,
        )
        .all()
    )

    # Agrupar por fecha
    from collections import defaultdict

    por_fecha: dict[date, dict] = defaultdict(lambda: {"total": 0, "erp": defaultdict(int), "ml": defaultdict(int)})

    for row in base:
        d = por_fecha[row.fecha_carga]
        d["total"] += 1
        if row.ssos_name:
            d["erp"][row.ssos_name] += 1
        if row.mlstatus:
            d["ml"][row.mlstatus] += 1

    dias = [
        EstadisticaDiaColectaItem(
            fecha=fecha,
            total=info["total"],
            por_estado_erp=dict(info["erp"]),
            por_estado_ml=dict(info["ml"]),
        )
        for fecha, info in sorted(por_fecha.items())
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

    sse_publish_bg("etiquetas:changed", {"hint": "reload"})

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

    sse_publish_bg("etiquetas:changed", {"hint": "reload"})

    return {"ok": True, "eliminadas": deleted}


@router.get(
    "/etiquetas-colecta/{shipping_id}/items",
    response_model=List[ItemEnvioColectaResponse],
    summary="Items/productos de un envío de colecta",
)
def items_envio_colecta(
    shipping_id: str,
    db: Session = Depends(get_db),
    current_user: Usuario = Depends(get_current_user),
) -> List[ItemEnvioColectaResponse]:
    """
    Devuelve los productos que componen un envío de colecta.

    Cadena: shipping_id → MercadoLibreOrderShipping.mlshippingid → mlo_id
    → MercadoLibreOrderDetail → mlo_title + item_id → TBItem.item_desc/item_code
    """
    _check_permiso(db, current_user, "envios_flex.ver")

    # Verificar que la etiqueta existe
    etiqueta = db.query(EtiquetaColecta).filter(EtiquetaColecta.shipping_id == shipping_id).first()
    if not etiqueta:
        raise HTTPException(404, f"Etiqueta {shipping_id} no encontrada")

    # Obtener mlo_ids vinculados a este shipping_id (puede haber varios)
    shipping_rows = (
        db.query(MercadoLibreOrderShipping.mlo_id)
        .filter(MercadoLibreOrderShipping.mlshippingid == shipping_id)
        .distinct()
        .all()
    )

    mlo_ids = [r.mlo_id for r in shipping_rows if r.mlo_id]
    if not mlo_ids:
        return []

    # Obtener items de MercadoLibreOrderDetail con JOIN a TBItem para código/desc
    items_query = (
        db.query(
            MercadoLibreOrderDetail.item_id,
            MercadoLibreOrderDetail.mlo_title,
            MercadoLibreOrderDetail.mlo_quantity,
            MercadoLibreOrderDetail.mlo_unit_price,
            TBItem.item_code,
            TBItem.item_desc,
        )
        .outerjoin(
            TBItem,
            MercadoLibreOrderDetail.item_id == TBItem.item_id,
        )
        .filter(MercadoLibreOrderDetail.mlo_id.in_(mlo_ids))
        .all()
    )

    # Agrupar por item_id para evitar duplicados (mismos items en distintas orders)
    seen: dict[str, dict] = {}
    for row in items_query:
        key = f"{row.item_id or 'none'}_{row.mlo_title or ''}"
        if key in seen:
            seen[key]["cantidad"] += float(row.mlo_quantity or 0)
        else:
            seen[key] = {
                "item_id": row.item_id,
                "item_code": row.item_code,
                "descripcion": row.mlo_title or row.item_desc or "Sin descripción",
                "cantidad": float(row.mlo_quantity or 0),
                "precio_unitario": float(row.mlo_unit_price) if row.mlo_unit_price else None,
            }

    return [ItemEnvioColectaResponse(**item) for item in seen.values()]
