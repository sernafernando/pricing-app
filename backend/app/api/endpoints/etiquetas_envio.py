"""
Endpoints para gestión de etiquetas de envío flex.

Permite:
- Subir archivos .zip/.txt con etiquetas ZPL de MercadoEnvíos
- Escanear QR individuales con pistola de código de barras
- Listar etiquetas con datos de envío (destinatario, dirección, CP, cordón)
- Asignar logísticas a etiquetas individual o masivamente
- Cambiar fecha de envío (reprogramar)
- Estadísticas de distribución por cordón, logística y estado

Los archivos ZPL contienen JSONs embebidos en los QR codes con formato:
{"id":"46458064834","sender_id":413658225,"hash_code":"...","security_digit":"0"}

El campo "id" del QR = mlshippingid en tb_mercadolibre_orders_shipping.
"""

import re
import io
import json
import zipfile
from io import BytesIO
from datetime import date, datetime, UTC

from fastapi import APIRouter, Depends, HTTPException, UploadFile, File, Query
from fastapi.responses import StreamingResponse
from sqlalchemy.orm import Session
from sqlalchemy import func, cast, String, and_, desc, Numeric
from typing import List, Optional
from pydantic import BaseModel, ConfigDict, Field

from app.core.database import get_db
from app.api.deps import get_current_user
from app.models.usuario import Usuario
from app.models.etiqueta_envio import EtiquetaEnvio
from app.models.logistica import Logistica
from app.models.mercadolibre_order_shipping import MercadoLibreOrderShipping
from app.models.codigo_postal_cordon import CodigoPostalCordon
from app.models.sale_order_header import SaleOrderHeader
from app.models.sale_order_status import SaleOrderStatus
from app.models.etiqueta_envio_audit import EtiquetaEnvioAudit
from app.models.operador import Operador
from app.models.operador_actividad import OperadorActividad
from app.models.logistica_costo_cordon import LogisticaCostoCordon
from app.services.etiqueta_enrichment_service import lanzar_enriquecimiento_background
from app.services.permisos_service import verificar_permiso

router = APIRouter()

# Regex para extraer JSONs del QR embebidos en ZPL
QR_JSON_REGEX = re.compile(r'\{"id":"[^}]+\}')


def _check_permiso(db: Session, user: Usuario, codigo: str) -> None:
    """Verifica permiso y lanza 403 si no lo tiene."""
    if not verificar_permiso(db, user, codigo):
        raise HTTPException(
            status_code=403,
            detail=f"No tenés permiso: {codigo}",
        )


# ── Schemas ──────────────────────────────────────────────────────────


class UploadResultResponse(BaseModel):
    """Resultado de la carga de etiquetas desde archivo."""

    total: int
    nuevas: int
    duplicadas: int
    errores: int = 0
    detalle_errores: List[str] = []


class ManualScanRequest(BaseModel):
    """Payload del escaneo manual con pistola."""

    json_data: str = Field(
        description='JSON raw del QR, ej: {"id":"46458064834","sender_id":413658225,...}',
    )


class ManualScanResponse(BaseModel):
    """Resultado del escaneo manual."""

    duplicada: bool
    shipping_id: str
    mensaje: str


class EtiquetaEnvioResponse(BaseModel):
    """Etiqueta con datos enriquecidos de envío, dirección y estado."""

    shipping_id: str
    sender_id: Optional[int] = None
    nombre_archivo: Optional[str] = None
    fecha_envio: date
    logistica_id: Optional[int] = None
    logistica_nombre: Optional[str] = None
    logistica_color: Optional[str] = None

    # Datos de ML shipping
    mlreceiver_name: Optional[str] = None
    mlstreet_name: Optional[str] = None
    mlstreet_number: Optional[str] = None
    mlzip_code: Optional[str] = None
    mlcity_name: Optional[str] = None
    mlstatus: Optional[str] = None

    # Cordón
    cordon: Optional[str] = None

    # Datos enriquecidos (ML webhook)
    latitud: Optional[float] = None
    longitud: Optional[float] = None
    direccion_completa: Optional[str] = None
    direccion_comentario: Optional[str] = None

    # Estado ERP
    ssos_id: Optional[int] = None
    ssos_name: Optional[str] = None
    ssos_color: Optional[str] = None

    # Pistoleado
    pistoleado_at: Optional[str] = None
    pistoleado_caja: Optional[str] = None
    pistoleado_operador_nombre: Optional[str] = None

    # Costo de envío (calculado desde logistica_costo_cordon, o override manual)
    costo_envio: Optional[float] = None
    costo_override: Optional[float] = None

    model_config = ConfigDict(from_attributes=True)


class EstadisticasEnvioResponse(BaseModel):
    """Estadísticas de distribución de etiquetas."""

    total: int
    por_cordon: dict[str, int]
    sin_cordon: int
    por_logistica: dict[str, int]
    sin_logistica: int
    por_estado_ml: dict[str, int]
    por_estado_erp: dict[str, int]
    costo_total: float = 0.0
    costo_por_logistica: dict[str, float] = {}


class AsignarLogisticaRequest(BaseModel):
    """Payload para asignar logística a una etiqueta."""

    logistica_id: Optional[int] = Field(
        None,
        description="ID de logística. None para desasignar.",
    )


class CambiarFechaRequest(BaseModel):
    """Payload para cambiar fecha de envío."""

    fecha_envio: date


class CostoOverrideRequest(BaseModel):
    """Payload para establecer o quitar un costo override en una etiqueta."""

    costo: Optional[float] = Field(
        None,
        ge=0,
        description="Costo manual. None para eliminar el override y volver al calculado.",
    )
    operador_id: int = Field(description="Operador autenticado con PIN")


class AsignarMasivoRequest(BaseModel):
    """Payload para asignación masiva de logística."""

    shipping_ids: List[str] = Field(min_length=1)
    logistica_id: int


# ── Schemas Pistoleado ───────────────────────────────────────────────


class PistolearRequest(BaseModel):
    """Payload del pistoleado: escaneo de QR de etiqueta en depósito."""

    shipping_id: str = Field(description="shipping_id extraído del QR de la etiqueta")
    caja: str = Field(max_length=50, description="Contenedor activo (CAJA 1, SUELTOS 1, etc.)")
    logistica_id: int = Field(description="Logística que el operador está pistoleando")
    operador_id: int = Field(description="Operador autenticado con PIN")


class PistolearResponse(BaseModel):
    """Resultado exitoso de un pistoleado."""

    ok: bool = True
    shipping_id: str
    caja: str
    operador: str
    receiver_name: Optional[str] = None
    ciudad: Optional[str] = None
    cordon: Optional[str] = None
    pistoleado_at: str
    count: int = Field(description="Total pistoleadas en esta sesión (fecha + logística + operador)")

    model_config = ConfigDict(from_attributes=True)


class PistoleadoConflictResponse(BaseModel):
    """Respuesta cuando la etiqueta ya fue pistoleada."""

    detail: str = "Ya pistoleada"
    pistoleado_por: str
    pistoleado_at: str
    pistoleado_caja: str


class PistoleadoStatsResponse(BaseModel):
    """Estadísticas de pistoleado para una fecha/logística."""

    total_etiquetas: int
    pistoleadas: int
    pendientes: int
    porcentaje: float
    por_caja: dict[str, int]
    por_operador: dict[str, int]


# ── Helpers ──────────────────────────────────────────────────────────


def _parse_qr_json(raw: str) -> dict:
    """
    Parsea el JSON del QR de la etiqueta ZPL.
    Retorna dict con shipping_id, sender_id, hash_code.
    Raises ValueError si el JSON no tiene el campo 'id'.
    """
    data = json.loads(raw)
    shipping_id = data.get("id")
    if not shipping_id:
        raise ValueError("JSON del QR no tiene campo 'id'")

    return {
        "shipping_id": str(shipping_id),
        "sender_id": data.get("sender_id"),
        "hash_code": data.get("hash_code"),
    }


def _extraer_qrs_de_texto(text: str) -> List[str]:
    """Extrae todos los JSONs de QR de un texto ZPL."""
    return QR_JSON_REGEX.findall(text)


def _soh_status_subquery(db: Session):
    """
    Subquery deduplicada: estado ERP por shipping_id.

    Un mismo mlshippingid puede tener múltiples filas en SaleOrderHeader
    (una por combinación comp_id/bra_id). Se toma el pedido más reciente
    (mayor soh_cd) con ROW_NUMBER OVER (PARTITION BY mlshippingid ORDER BY soh_cd DESC).
    """
    ranked = (
        db.query(
            cast(SaleOrderHeader.mlshippingid, String).label("shipping_id_str"),
            SaleOrderHeader.ssos_id.label("soh_ssos_id"),
            func.row_number()
            .over(
                partition_by=SaleOrderHeader.mlshippingid,
                order_by=desc(SaleOrderHeader.soh_cd),
            )
            .label("rn"),
        )
        .filter(SaleOrderHeader.mlshippingid.isnot(None))
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


def _insertar_etiqueta(
    db: Session,
    shipping_id: str,
    sender_id: Optional[int],
    hash_code: Optional[str],
    nombre_archivo: Optional[str],
    fecha_envio: date,
) -> bool:
    """
    Inserta una etiqueta si no existe.
    Retorna True si se insertó (nueva), False si ya existía (duplicada).
    """
    existente = db.query(EtiquetaEnvio).filter(EtiquetaEnvio.shipping_id == shipping_id).first()
    if existente:
        return False

    etiqueta = EtiquetaEnvio(
        shipping_id=shipping_id,
        sender_id=sender_id,
        hash_code=hash_code,
        nombre_archivo=nombre_archivo,
        fecha_envio=fecha_envio,
    )
    db.add(etiqueta)
    return True


# ── Endpoints ────────────────────────────────────────────────────────


@router.post(
    "/etiquetas-envio/upload",
    response_model=UploadResultResponse,
    summary="Subir archivo ZPL (.zip o .txt) con etiquetas",
)
def upload_etiquetas(
    file: UploadFile = File(..., description="Archivo .zip o .txt con etiquetas ZPL"),
    db: Session = Depends(get_db),
    current_user: Usuario = Depends(get_current_user),
) -> UploadResultResponse:
    """
    Recibe un .zip (que contiene .txt) o directamente un .txt con etiquetas ZPL.
    Extrae los JSONs de los QR codes, parsea shipping_id/sender_id/hash_code
    e inserta en etiquetas_envio con ON CONFLICT(shipping_id) DO NOTHING.
    """
    _check_permiso(db, current_user, "envios_flex.subir_etiquetas")

    if not file.filename:
        raise HTTPException(400, "Archivo sin nombre")

    filename = file.filename.lower()
    if not filename.endswith((".zip", ".txt")):
        raise HTTPException(400, "Solo se aceptan archivos .zip o .txt")

    contents = file.file.read()
    nombre_archivo = file.filename
    text_content = ""

    if filename.endswith(".zip"):
        try:
            with zipfile.ZipFile(BytesIO(contents)) as zf:
                # Buscar el primer .txt dentro del zip
                txt_files = [
                    name for name in zf.namelist() if name.lower().endswith(".txt") and not name.startswith("__MACOSX")
                ]
                if not txt_files:
                    raise HTTPException(400, "El .zip no contiene archivos .txt")

                text_content = zf.read(txt_files[0]).decode("utf-8", errors="replace")
        except zipfile.BadZipFile:
            raise HTTPException(400, "Archivo .zip inválido o corrupto")
    else:
        text_content = contents.decode("utf-8", errors="replace")

    # Extraer QR JSONs
    qr_jsons = _extraer_qrs_de_texto(text_content)

    if not qr_jsons:
        raise HTTPException(400, "No se encontraron etiquetas QR en el archivo")

    total = len(qr_jsons)
    nuevas = 0
    duplicadas = 0
    errores = 0
    detalle_errores: List[str] = []
    nuevos_shipping_ids: List[str] = []
    hoy = date.today()

    for raw_json in qr_jsons:
        try:
            parsed = _parse_qr_json(raw_json)
            es_nueva = _insertar_etiqueta(
                db=db,
                shipping_id=parsed["shipping_id"],
                sender_id=parsed["sender_id"],
                hash_code=parsed["hash_code"],
                nombre_archivo=nombre_archivo,
                fecha_envio=hoy,
            )
            if es_nueva:
                nuevas += 1
                nuevos_shipping_ids.append(parsed["shipping_id"])
            else:
                duplicadas += 1
        except (json.JSONDecodeError, ValueError) as e:
            errores += 1
            detalle_errores.append(f"Error parseando QR: {str(e)[:100]}")

    try:
        db.commit()
    except Exception as e:
        db.rollback()
        raise HTTPException(500, f"Error guardando en base de datos: {str(e)}")

    # Enriquecer etiquetas nuevas en background (coords, dirección, comentario)
    lanzar_enriquecimiento_background(nuevos_shipping_ids)

    return UploadResultResponse(
        total=total,
        nuevas=nuevas,
        duplicadas=duplicadas,
        errores=errores,
        detalle_errores=detalle_errores[:20],
    )


@router.post(
    "/etiquetas-envio/manual",
    response_model=ManualScanResponse,
    summary="Registrar etiqueta individual (escaneo con pistola)",
)
def registrar_manual(
    payload: ManualScanRequest,
    db: Session = Depends(get_db),
    current_user: Usuario = Depends(get_current_user),
) -> ManualScanResponse:
    """
    Recibe el JSON del QR escaneado con pistola de código de barras.
    Inserta la etiqueta si no existe.
    """
    _check_permiso(db, current_user, "envios_flex.subir_etiquetas")

    try:
        parsed = _parse_qr_json(payload.json_data)
    except (json.JSONDecodeError, ValueError) as e:
        raise HTTPException(400, f"JSON inválido: {str(e)}")

    es_nueva = _insertar_etiqueta(
        db=db,
        shipping_id=parsed["shipping_id"],
        sender_id=parsed["sender_id"],
        hash_code=parsed["hash_code"],
        nombre_archivo="escaneo_manual",
        fecha_envio=date.today(),
    )

    try:
        db.commit()
    except Exception as e:
        db.rollback()
        raise HTTPException(500, f"Error guardando: {str(e)}")

    shipping_id = parsed["shipping_id"]

    if es_nueva:
        # Enriquecer en background (coords, dirección, comentario)
        lanzar_enriquecimiento_background([shipping_id])

        return ManualScanResponse(
            duplicada=False,
            shipping_id=shipping_id,
            mensaje=f"Cargado: {shipping_id}",
        )
    else:
        return ManualScanResponse(
            duplicada=True,
            shipping_id=shipping_id,
            mensaje=f"Ya existía: {shipping_id}",
        )


@router.get(
    "/etiquetas-envio",
    response_model=List[EtiquetaEnvioResponse],
    summary="Listar etiquetas con datos de envío",
)
def listar_etiquetas(
    fecha_envio: Optional[date] = Query(None, description="Filtrar por fecha de envío exacta"),
    fecha_desde: Optional[date] = Query(None, description="Filtrar desde fecha (inclusive)"),
    fecha_hasta: Optional[date] = Query(None, description="Filtrar hasta fecha (inclusive)"),
    cordon: Optional[str] = Query(None, description="Filtrar por cordón"),
    logistica_id: Optional[int] = Query(None, description="Filtrar por logística"),
    sin_logistica: bool = Query(False, description="Solo etiquetas sin logística asignada"),
    mlstatus: Optional[str] = Query(None, description="Filtrar por estado ML"),
    ssos_id: Optional[int] = Query(None, description="Filtrar por estado ERP"),
    search: Optional[str] = Query(None, description="Buscar por shipping_id, destinatario o dirección"),
    db: Session = Depends(get_db),
    current_user: Usuario = Depends(get_current_user),
) -> List[EtiquetaEnvioResponse]:
    """
    Lista etiquetas de envío con JOINs a:
    - tb_mercadolibre_orders_shipping (datos del envío)
    - cp_cordones (cordón del CP)
    - tb_sale_order_header (ssos_id del pedido ERP)
    - tb_sale_order_status (nombre y color del estado)
    - logisticas (nombre y color de la logística)
    """
    _check_permiso(db, current_user, "envios_flex.ver")

    soh_sub = _soh_status_subquery(db)

    # Subquery: costo vigente por (logistica_id, cordon) donde vigente_desde <= hoy.
    # cp_cordones usa tildes (Cordón) pero logistica_costo_cordon no (Cordon),
    # así que normalizamos con REPLACE en la condición del JOIN.
    hoy = date.today()
    max_costo_sub = (
        db.query(
            LogisticaCostoCordon.logistica_id.label("costo_logistica_id"),
            LogisticaCostoCordon.cordon.label("costo_cordon"),
            func.max(LogisticaCostoCordon.vigente_desde).label("max_vigente"),
        )
        .filter(LogisticaCostoCordon.vigente_desde <= hoy)
        .group_by(
            LogisticaCostoCordon.logistica_id,
            LogisticaCostoCordon.cordon,
        )
        .subquery()
    )

    costo_sub = (
        db.query(
            LogisticaCostoCordon.logistica_id.label("costo_log_id"),
            LogisticaCostoCordon.cordon.label("costo_cordon_val"),
            LogisticaCostoCordon.costo.label("costo_valor"),
        )
        .join(
            max_costo_sub,
            and_(
                LogisticaCostoCordon.logistica_id == max_costo_sub.c.costo_logistica_id,
                LogisticaCostoCordon.cordon == max_costo_sub.c.costo_cordon,
                LogisticaCostoCordon.vigente_desde == max_costo_sub.c.max_vigente,
            ),
        )
        .subquery()
    )

    # Expresión para normalizar cordón: "Cordón 1" → "Cordon 1" (quitar tilde)
    cordon_normalizado = func.replace(CodigoPostalCordon.cordon, "ó", "o")

    query = (
        db.query(
            EtiquetaEnvio.shipping_id,
            EtiquetaEnvio.sender_id,
            EtiquetaEnvio.nombre_archivo,
            EtiquetaEnvio.fecha_envio,
            EtiquetaEnvio.logistica_id,
            EtiquetaEnvio.latitud,
            EtiquetaEnvio.longitud,
            EtiquetaEnvio.direccion_completa,
            EtiquetaEnvio.direccion_comentario,
            EtiquetaEnvio.pistoleado_at,
            EtiquetaEnvio.pistoleado_caja,
            Operador.nombre.label("pistoleado_operador_nombre"),
            Logistica.nombre.label("logistica_nombre"),
            Logistica.color.label("logistica_color"),
            MercadoLibreOrderShipping.mlreceiver_name,
            MercadoLibreOrderShipping.mlstreet_name,
            MercadoLibreOrderShipping.mlstreet_number,
            MercadoLibreOrderShipping.mlzip_code,
            MercadoLibreOrderShipping.mlcity_name,
            MercadoLibreOrderShipping.mlstatus,
            CodigoPostalCordon.cordon,
            soh_sub.c.soh_ssos_id.label("ssos_id"),
            SaleOrderStatus.ssos_name,
            SaleOrderStatus.ssos_color,
            func.coalesce(
                cast(EtiquetaEnvio.costo_override, Numeric(12, 2)),
                cast(costo_sub.c.costo_valor, Numeric(12, 2)),
            ).label("costo_envio"),
            EtiquetaEnvio.costo_override,
        )
        .outerjoin(
            Logistica,
            EtiquetaEnvio.logistica_id == Logistica.id,
        )
        .outerjoin(
            MercadoLibreOrderShipping,
            EtiquetaEnvio.shipping_id == MercadoLibreOrderShipping.mlshippingid,
        )
        .outerjoin(
            CodigoPostalCordon,
            MercadoLibreOrderShipping.mlzip_code == CodigoPostalCordon.codigo_postal,
        )
        .outerjoin(
            soh_sub,
            soh_sub.c.shipping_id_str == EtiquetaEnvio.shipping_id,
        )
        .outerjoin(
            SaleOrderStatus,
            soh_sub.c.soh_ssos_id == SaleOrderStatus.ssos_id,
        )
        .outerjoin(
            Operador,
            EtiquetaEnvio.pistoleado_operador_id == Operador.id,
        )
        .outerjoin(
            costo_sub,
            and_(
                costo_sub.c.costo_log_id == EtiquetaEnvio.logistica_id,
                costo_sub.c.costo_cordon_val == cordon_normalizado,
            ),
        )
    )

    # ── Filtros ──────────────────────────────────────────────────

    # fecha_envio = exacta (backward compatible), fecha_desde/fecha_hasta = rango
    if fecha_envio:
        query = query.filter(EtiquetaEnvio.fecha_envio == fecha_envio)
    else:
        if fecha_desde:
            query = query.filter(EtiquetaEnvio.fecha_envio >= fecha_desde)
        if fecha_hasta:
            query = query.filter(EtiquetaEnvio.fecha_envio <= fecha_hasta)

    if cordon:
        query = query.filter(CodigoPostalCordon.cordon == cordon)

    if logistica_id is not None:
        query = query.filter(EtiquetaEnvio.logistica_id == logistica_id)

    if sin_logistica:
        query = query.filter(EtiquetaEnvio.logistica_id.is_(None))

    if mlstatus:
        query = query.filter(MercadoLibreOrderShipping.mlstatus == mlstatus)

    if ssos_id is not None:
        query = query.filter(soh_sub.c.soh_ssos_id == ssos_id)

    if search:
        search_term = f"%{search}%"
        query = query.filter(
            (EtiquetaEnvio.shipping_id.ilike(search_term))
            | (MercadoLibreOrderShipping.mlreceiver_name.ilike(search_term))
            | (MercadoLibreOrderShipping.mlstreet_name.ilike(search_term))
            | (MercadoLibreOrderShipping.mlcity_name.ilike(search_term))
        )

    # Ordenar por shipping_id desc (más recientes primero)
    query = query.order_by(EtiquetaEnvio.shipping_id.desc())

    rows = query.all()

    return [
        EtiquetaEnvioResponse(
            shipping_id=row.shipping_id,
            sender_id=row.sender_id,
            nombre_archivo=row.nombre_archivo,
            fecha_envio=row.fecha_envio,
            logistica_id=row.logistica_id,
            logistica_nombre=row.logistica_nombre,
            logistica_color=row.logistica_color,
            mlreceiver_name=row.mlreceiver_name,
            mlstreet_name=row.mlstreet_name,
            mlstreet_number=row.mlstreet_number,
            mlzip_code=row.mlzip_code,
            mlcity_name=row.mlcity_name,
            mlstatus=row.mlstatus,
            cordon=row.cordon,
            latitud=row.latitud,
            longitud=row.longitud,
            direccion_completa=row.direccion_completa,
            direccion_comentario=row.direccion_comentario,
            ssos_id=row.ssos_id,
            ssos_name=row.ssos_name,
            ssos_color=row.ssos_color,
            pistoleado_at=str(row.pistoleado_at) if row.pistoleado_at else None,
            pistoleado_caja=row.pistoleado_caja,
            pistoleado_operador_nombre=row.pistoleado_operador_nombre,
            costo_envio=float(row.costo_envio) if row.costo_envio is not None else None,
            costo_override=float(row.costo_override) if row.costo_override is not None else None,
        )
        for row in rows
    ]


@router.get(
    "/etiquetas-envio/estadisticas",
    response_model=EstadisticasEnvioResponse,
    summary="Estadísticas de distribución de etiquetas",
)
def estadisticas_etiquetas(
    fecha_envio: Optional[date] = Query(None, description="Fecha de envío exacta (por defecto hoy)"),
    fecha_desde: Optional[date] = Query(None, description="Filtrar desde fecha (inclusive)"),
    fecha_hasta: Optional[date] = Query(None, description="Filtrar hasta fecha (inclusive)"),
    db: Session = Depends(get_db),
    current_user: Usuario = Depends(get_current_user),
) -> EstadisticasEnvioResponse:
    """Distribución de etiquetas por cordón, logística y estado."""
    _check_permiso(db, current_user, "envios_flex.ver")

    # Determinar filtro de fechas: exacta (backward compatible) o rango
    if fecha_envio:
        fecha_filter = EtiquetaEnvio.fecha_envio == fecha_envio
        fecha_costo = fecha_envio
    elif fecha_desde or fecha_hasta:
        conditions = []
        if fecha_desde:
            conditions.append(EtiquetaEnvio.fecha_envio >= fecha_desde)
        if fecha_hasta:
            conditions.append(EtiquetaEnvio.fecha_envio <= fecha_hasta)
        fecha_filter = and_(*conditions) if len(conditions) > 1 else conditions[0]
        fecha_costo = fecha_hasta or fecha_desde or date.today()
    else:
        fecha_filter = EtiquetaEnvio.fecha_envio == date.today()
        fecha_costo = date.today()

    # Base: etiquetas filtradas
    base_query = db.query(EtiquetaEnvio).filter(fecha_filter)

    total = base_query.count()

    # Por cordón
    cordon_rows = (
        db.query(
            CodigoPostalCordon.cordon,
            func.count().label("cantidad"),
        )
        .join(
            MercadoLibreOrderShipping,
            MercadoLibreOrderShipping.mlzip_code == CodigoPostalCordon.codigo_postal,
        )
        .join(
            EtiquetaEnvio,
            EtiquetaEnvio.shipping_id == MercadoLibreOrderShipping.mlshippingid,
        )
        .filter(
            fecha_filter,
            CodigoPostalCordon.cordon.isnot(None),
        )
        .group_by(CodigoPostalCordon.cordon)
        .all()
    )
    por_cordon = {row.cordon: row.cantidad for row in cordon_rows}
    con_cordon = sum(por_cordon.values())

    # Por logística
    logistica_rows = (
        db.query(
            Logistica.nombre,
            func.count().label("cantidad"),
        )
        .join(EtiquetaEnvio, EtiquetaEnvio.logistica_id == Logistica.id)
        .filter(fecha_filter)
        .group_by(Logistica.nombre)
        .all()
    )
    por_logistica = {row.nombre: row.cantidad for row in logistica_rows}
    con_logistica = sum(por_logistica.values())

    # Por estado ML
    ml_status_rows = (
        db.query(
            MercadoLibreOrderShipping.mlstatus,
            func.count().label("cantidad"),
        )
        .join(
            EtiquetaEnvio,
            EtiquetaEnvio.shipping_id == MercadoLibreOrderShipping.mlshippingid,
        )
        .filter(
            fecha_filter,
            MercadoLibreOrderShipping.mlstatus.isnot(None),
        )
        .group_by(MercadoLibreOrderShipping.mlstatus)
        .all()
    )
    por_estado_ml = {row.mlstatus: row.cantidad for row in ml_status_rows}

    # Por estado ERP
    soh_sub = _soh_status_subquery(db)

    erp_status_rows = (
        db.query(
            SaleOrderStatus.ssos_name,
            func.count().label("cantidad"),
        )
        .join(soh_sub, soh_sub.c.soh_ssos_id == SaleOrderStatus.ssos_id)
        .join(
            EtiquetaEnvio,
            EtiquetaEnvio.shipping_id == soh_sub.c.shipping_id_str,
        )
        .filter(fecha_filter)
        .group_by(SaleOrderStatus.ssos_name)
        .all()
    )
    por_estado_erp = {row.ssos_name: row.cantidad for row in erp_status_rows}

    # ── Costos de envío ─────────────────────────────────────────
    # Subquery: costo vigente por (logistica_id, cordon) donde vigente_desde <= fecha_costo
    max_costo_stats = (
        db.query(
            LogisticaCostoCordon.logistica_id.label("costo_logistica_id"),
            LogisticaCostoCordon.cordon.label("costo_cordon"),
            func.max(LogisticaCostoCordon.vigente_desde).label("max_vigente"),
        )
        .filter(LogisticaCostoCordon.vigente_desde <= fecha_costo)
        .group_by(
            LogisticaCostoCordon.logistica_id,
            LogisticaCostoCordon.cordon,
        )
        .subquery()
    )

    costo_stats = (
        db.query(
            LogisticaCostoCordon.logistica_id.label("costo_log_id"),
            LogisticaCostoCordon.cordon.label("costo_cordon_val"),
            LogisticaCostoCordon.costo.label("costo_valor"),
        )
        .join(
            max_costo_stats,
            and_(
                LogisticaCostoCordon.logistica_id == max_costo_stats.c.costo_logistica_id,
                LogisticaCostoCordon.cordon == max_costo_stats.c.costo_cordon,
                LogisticaCostoCordon.vigente_desde == max_costo_stats.c.max_vigente,
            ),
        )
        .subquery()
    )

    # Normalizar cordón: "Cordón 1" → "Cordon 1"
    cordon_norm = func.replace(CodigoPostalCordon.cordon, "ó", "o")

    # costo_efectivo: si la etiqueta tiene costo_override, usar ese;
    # sino usar el costo calculado de logistica_costo_cordon.
    costo_efectivo = func.coalesce(
        cast(EtiquetaEnvio.costo_override, Numeric(12, 2)),
        cast(costo_stats.c.costo_valor, Numeric(12, 2)),
    )

    costo_rows = (
        db.query(
            Logistica.nombre.label("log_nombre"),
            func.coalesce(func.sum(costo_efectivo), 0).label("costo_sum"),
        )
        .join(EtiquetaEnvio, EtiquetaEnvio.logistica_id == Logistica.id)
        .join(
            MercadoLibreOrderShipping,
            EtiquetaEnvio.shipping_id == MercadoLibreOrderShipping.mlshippingid,
        )
        .join(
            CodigoPostalCordon,
            MercadoLibreOrderShipping.mlzip_code == CodigoPostalCordon.codigo_postal,
        )
        .outerjoin(
            costo_stats,
            and_(
                costo_stats.c.costo_log_id == EtiquetaEnvio.logistica_id,
                costo_stats.c.costo_cordon_val == cordon_norm,
            ),
        )
        .filter(
            fecha_filter,
            CodigoPostalCordon.cordon.isnot(None),
        )
        .group_by(Logistica.nombre)
        .all()
    )

    costo_por_logistica = {row.log_nombre: float(row.costo_sum) for row in costo_rows}
    costo_total = sum(costo_por_logistica.values())

    # Sumar también etiquetas con costo_override que NO tienen logística
    # asignada (no entran en la query agrupada por logística)
    costo_sin_logistica = (
        db.query(
            func.coalesce(func.sum(cast(EtiquetaEnvio.costo_override, Numeric(12, 2))), 0),
        )
        .filter(
            fecha_filter,
            EtiquetaEnvio.logistica_id.is_(None),
            EtiquetaEnvio.costo_override.isnot(None),
        )
        .scalar()
    )
    costo_total += float(costo_sin_logistica or 0)

    return EstadisticasEnvioResponse(
        total=total,
        por_cordon=por_cordon,
        sin_cordon=max(0, total - con_cordon),
        por_logistica=por_logistica,
        sin_logistica=max(0, total - con_logistica),
        por_estado_ml=por_estado_ml,
        por_estado_erp=por_estado_erp,
        costo_total=costo_total,
        costo_por_logistica=costo_por_logistica,
    )


# ── Columnas disponibles para export ──────────────────────────────

EXPORT_COLUMNS = {
    "shipping_id": "Shipping ID",
    "fecha_envio": "Fecha Envío",
    "destinatario": "Destinatario",
    "direccion": "Dirección",
    "cp": "CP",
    "localidad": "Localidad",
    "cordon": "Cordón",
    "logistica": "Logística",
    "costo_envio": "Costo Envío",
    "estado_ml": "Estado ML",
    "estado_erp": "Estado ERP",
    "pistoleado": "Pistoleado",
    "caja": "Caja",
}


@router.get(
    "/etiquetas-envio/export",
    summary="Exportar etiquetas a Excel (XLSX)",
    response_class=StreamingResponse,
)
def exportar_etiquetas(
    fecha_desde: date = Query(..., description="Desde fecha (inclusive)"),
    fecha_hasta: date = Query(..., description="Hasta fecha (inclusive)"),
    columnas: Optional[str] = Query(
        None,
        description="Columnas a incluir (comma-separated). Si no se especifica, todas.",
    ),
    cordon: Optional[str] = Query(None, description="Filtrar por cordón"),
    logistica_id: Optional[int] = Query(None, description="Filtrar por logística"),
    sin_logistica: bool = Query(False, description="Solo sin logística asignada"),
    mlstatus: Optional[str] = Query(None, description="Filtrar por estado ML"),
    search: Optional[str] = Query(None, description="Buscar por shipping_id, destinatario o dirección"),
    db: Session = Depends(get_db),
    current_user: Usuario = Depends(get_current_user),
) -> StreamingResponse:
    """
    Exporta etiquetas filtradas a un archivo Excel (.xlsx).
    Soporta selección de columnas y todos los filtros de la vista.
    """
    _check_permiso(db, current_user, "envios_flex.exportar")

    from openpyxl import Workbook
    from openpyxl.styles import Font, Alignment, PatternFill

    # Validar columnas solicitadas
    if columnas:
        cols_solicitadas = [c.strip() for c in columnas.split(",") if c.strip()]
        invalidas = [c for c in cols_solicitadas if c not in EXPORT_COLUMNS]
        if invalidas:
            raise HTTPException(400, f"Columnas inválidas: {', '.join(invalidas)}")
    else:
        cols_solicitadas = list(EXPORT_COLUMNS.keys())

    # Reusar subquery deduplicada de estado ERP
    soh_sub = _soh_status_subquery(db)

    hoy_export = date.today()
    max_costo_exp = (
        db.query(
            LogisticaCostoCordon.logistica_id.label("costo_logistica_id"),
            LogisticaCostoCordon.cordon.label("costo_cordon"),
            func.max(LogisticaCostoCordon.vigente_desde).label("max_vigente"),
        )
        .filter(LogisticaCostoCordon.vigente_desde <= hoy_export)
        .group_by(LogisticaCostoCordon.logistica_id, LogisticaCostoCordon.cordon)
        .subquery()
    )

    costo_exp = (
        db.query(
            LogisticaCostoCordon.logistica_id.label("costo_log_id"),
            LogisticaCostoCordon.cordon.label("costo_cordon_val"),
            LogisticaCostoCordon.costo.label("costo_valor"),
        )
        .join(
            max_costo_exp,
            and_(
                LogisticaCostoCordon.logistica_id == max_costo_exp.c.costo_logistica_id,
                LogisticaCostoCordon.cordon == max_costo_exp.c.costo_cordon,
                LogisticaCostoCordon.vigente_desde == max_costo_exp.c.max_vigente,
            ),
        )
        .subquery()
    )

    cordon_norm_exp = func.replace(CodigoPostalCordon.cordon, "ó", "o")

    query = (
        db.query(
            EtiquetaEnvio.shipping_id,
            EtiquetaEnvio.fecha_envio,
            EtiquetaEnvio.pistoleado_at,
            EtiquetaEnvio.pistoleado_caja,
            Operador.nombre.label("pistoleado_operador_nombre"),
            Logistica.nombre.label("logistica_nombre"),
            MercadoLibreOrderShipping.mlreceiver_name,
            MercadoLibreOrderShipping.mlstreet_name,
            MercadoLibreOrderShipping.mlstreet_number,
            MercadoLibreOrderShipping.mlzip_code,
            MercadoLibreOrderShipping.mlcity_name,
            MercadoLibreOrderShipping.mlstatus,
            CodigoPostalCordon.cordon,
            SaleOrderStatus.ssos_name,
            func.coalesce(
                cast(EtiquetaEnvio.costo_override, Numeric(12, 2)),
                cast(costo_exp.c.costo_valor, Numeric(12, 2)),
            ).label("costo_envio"),
        )
        .outerjoin(Logistica, EtiquetaEnvio.logistica_id == Logistica.id)
        .outerjoin(
            MercadoLibreOrderShipping,
            EtiquetaEnvio.shipping_id == MercadoLibreOrderShipping.mlshippingid,
        )
        .outerjoin(
            CodigoPostalCordon,
            MercadoLibreOrderShipping.mlzip_code == CodigoPostalCordon.codigo_postal,
        )
        .outerjoin(soh_sub, soh_sub.c.shipping_id_str == EtiquetaEnvio.shipping_id)
        .outerjoin(SaleOrderStatus, soh_sub.c.soh_ssos_id == SaleOrderStatus.ssos_id)
        .outerjoin(Operador, EtiquetaEnvio.pistoleado_operador_id == Operador.id)
        .outerjoin(
            costo_exp,
            and_(
                costo_exp.c.costo_log_id == EtiquetaEnvio.logistica_id,
                costo_exp.c.costo_cordon_val == cordon_norm_exp,
            ),
        )
    )

    # Filtros
    query = query.filter(
        EtiquetaEnvio.fecha_envio >= fecha_desde,
        EtiquetaEnvio.fecha_envio <= fecha_hasta,
    )

    if cordon:
        query = query.filter(CodigoPostalCordon.cordon == cordon)
    if logistica_id is not None:
        query = query.filter(EtiquetaEnvio.logistica_id == logistica_id)
    if sin_logistica:
        query = query.filter(EtiquetaEnvio.logistica_id.is_(None))
    if mlstatus:
        query = query.filter(MercadoLibreOrderShipping.mlstatus == mlstatus)
    if search:
        search_term = f"%{search}%"
        query = query.filter(
            (EtiquetaEnvio.shipping_id.ilike(search_term))
            | (MercadoLibreOrderShipping.mlreceiver_name.ilike(search_term))
            | (MercadoLibreOrderShipping.mlstreet_name.ilike(search_term))
            | (MercadoLibreOrderShipping.mlcity_name.ilike(search_term))
        )

    query = query.order_by(EtiquetaEnvio.fecha_envio, EtiquetaEnvio.shipping_id.desc())
    rows = query.all()

    # ── Generar XLSX ──────────────────────────────────────────
    wb = Workbook()
    ws = wb.active
    ws.title = "Envíos Flex"

    header_fill = PatternFill(start_color="366092", end_color="366092", fill_type="solid")
    header_font = Font(bold=True, color="FFFFFF", size=11)
    header_alignment = Alignment(horizontal="center", vertical="center", wrap_text=True)

    # Headers
    headers = [EXPORT_COLUMNS[c] for c in cols_solicitadas]
    for col_idx, header in enumerate(headers, start=1):
        cell = ws.cell(row=1, column=col_idx, value=header)
        cell.fill = header_fill
        cell.font = header_font
        cell.alignment = header_alignment

    # Mapeo de columna → valor
    def get_cell_value(col_key: str, row: object) -> object:
        """Extrae el valor de una columna para una fila de resultados."""
        if col_key == "shipping_id":
            return row.shipping_id
        elif col_key == "fecha_envio":
            return row.fecha_envio
        elif col_key == "destinatario":
            return row.mlreceiver_name or ""
        elif col_key == "direccion":
            parts = [row.mlstreet_name or "", row.mlstreet_number or ""]
            return " ".join(p for p in parts if p).strip()
        elif col_key == "cp":
            return row.mlzip_code or ""
        elif col_key == "localidad":
            return row.mlcity_name or ""
        elif col_key == "cordon":
            return row.cordon or ""
        elif col_key == "logistica":
            return row.logistica_nombre or ""
        elif col_key == "costo_envio":
            return float(row.costo_envio) if row.costo_envio is not None else ""
        elif col_key == "estado_ml":
            return row.mlstatus or ""
        elif col_key == "estado_erp":
            return row.ssos_name or ""
        elif col_key == "pistoleado":
            if row.pistoleado_at:
                ts = str(row.pistoleado_at)[:16]  # YYYY-MM-DD HH:MM
                operador = row.pistoleado_operador_nombre or ""
                return f"{ts} — {operador}" if operador else ts
            return ""
        elif col_key == "caja":
            return row.pistoleado_caja or ""
        return ""

    # Datos
    for row_idx, row in enumerate(rows, start=2):
        for col_idx, col_key in enumerate(cols_solicitadas, start=1):
            ws.cell(row=row_idx, column=col_idx, value=get_cell_value(col_key, row))

    # Anchos automáticos (estimados)
    col_widths = {
        "shipping_id": 16,
        "fecha_envio": 14,
        "destinatario": 25,
        "direccion": 35,
        "cp": 8,
        "localidad": 20,
        "cordon": 12,
        "logistica": 18,
        "costo_envio": 14,
        "estado_ml": 18,
        "estado_erp": 18,
        "pistoleado": 22,
        "caja": 14,
    }
    for col_idx, col_key in enumerate(cols_solicitadas, start=1):
        col_letter = ws.cell(row=1, column=col_idx).column_letter
        ws.column_dimensions[col_letter].width = col_widths.get(col_key, 15)

    # Generar archivo en memoria
    output = io.BytesIO()
    wb.save(output)
    output.seek(0)

    filename = f"envios_flex_{fecha_desde}_{fecha_hasta}.xlsx"

    return StreamingResponse(
        output,
        media_type="application/vnd.openxmlformats-officedocument.spreadsheetml.sheet",
        headers={"Content-Disposition": f'attachment; filename="{filename}"'},
    )


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
    operador = (
        db.query(Operador)
        .filter(Operador.id == payload.operador_id, Operador.activo.is_(True))
        .first()
    )
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

    return {
        "ok": True,
        "actualizadas": updated,
        "logistica_id": payload.logistica_id,
        "logistica_nombre": logistica.nombre,
    }


class BorrarEtiquetasRequest(BaseModel):
    """Payload para borrar etiquetas con auditoría."""

    shipping_ids: List[str] = Field(min_length=1)
    comment: Optional[str] = Field(None, max_length=500, description="Motivo del borrado")


@router.delete(
    "/etiquetas-envio",
    response_model=dict,
    summary="Borrar etiquetas de envío (con auditoría)",
)
def borrar_etiquetas(
    payload: BorrarEtiquetasRequest,
    db: Session = Depends(get_db),
    current_user: Usuario = Depends(get_current_user),
) -> dict:
    """
    Elimina etiquetas por shipping_id.
    Antes de borrar, copia cada etiqueta a etiquetas_envio_audit
    con el usuario que borró, timestamp y comentario opcional.
    """
    _check_permiso(db, current_user, "envios_flex.eliminar")

    # Buscar etiquetas a borrar
    etiquetas = db.query(EtiquetaEnvio).filter(EtiquetaEnvio.shipping_id.in_(payload.shipping_ids)).all()

    if not etiquetas:
        raise HTTPException(404, "No se encontraron etiquetas para borrar")

    # Copiar a audit antes de borrar
    for etiq in etiquetas:
        audit = EtiquetaEnvioAudit(
            shipping_id=etiq.shipping_id,
            sender_id=etiq.sender_id,
            hash_code=etiq.hash_code,
            nombre_archivo=etiq.nombre_archivo,
            fecha_envio=etiq.fecha_envio,
            logistica_id=etiq.logistica_id,
            latitud=etiq.latitud,
            longitud=etiq.longitud,
            direccion_completa=etiq.direccion_completa,
            direccion_comentario=etiq.direccion_comentario,
            pistoleado_at=etiq.pistoleado_at,
            pistoleado_caja=etiq.pistoleado_caja,
            pistoleado_operador_id=etiq.pistoleado_operador_id,
            original_created_at=etiq.created_at,
            original_updated_at=etiq.updated_at,
            deleted_by=current_user.id,
            delete_comment=payload.comment,
        )
        db.add(audit)

    # Borrar originales
    deleted = (
        db.query(EtiquetaEnvio)
        .filter(EtiquetaEnvio.shipping_id.in_(payload.shipping_ids))
        .delete(synchronize_session="fetch")
    )

    db.commit()

    return {"ok": True, "eliminadas": deleted}


# ── Pistoleado ───────────────────────────────────────────────────────


@router.post(
    "/etiquetas-envio/pistolear",
    response_model=PistolearResponse,
    summary="Pistolear etiqueta (escaneo de paquete en depósito)",
    responses={
        409: {"model": PistoleadoConflictResponse, "description": "Ya pistoleada"},
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
    Validaciones:
    1. La etiqueta debe existir en el sistema.
    2. No debe haber sido pistoleada antes (duplicado → 409).
    3. La logística asignada debe coincidir con la que está pistoleando (→ 422).

    Side effects:
    - Graba pistoleado_at, pistoleado_caja, pistoleado_operador_id.
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

    # Validar duplicado
    if etiqueta.pistoleado_at is not None:
        # Obtener nombre del operador que pistoleó antes
        op_previo = db.query(Operador).filter(Operador.id == etiqueta.pistoleado_operador_id).first()
        nombre_previo = op_previo.nombre if op_previo else "Desconocido"
        raise HTTPException(
            409,
            detail={
                "detail": "Ya pistoleada",
                "pistoleado_por": nombre_previo,
                "pistoleado_at": str(etiqueta.pistoleado_at),
                "pistoleado_caja": etiqueta.pistoleado_caja or "",
            },
        )

    # Validar logística coincide (bloqueo estricto)
    if etiqueta.logistica_id is not None and etiqueta.logistica_id != payload.logistica_id:
        logistica_etiq = db.query(Logistica).filter(Logistica.id == etiqueta.logistica_id).first()
        logistica_pistoleando = db.query(Logistica).filter(Logistica.id == payload.logistica_id).first()
        raise HTTPException(
            422,
            detail={
                "detail": "Logística no coincide",
                "etiqueta_logistica": logistica_etiq.nombre if logistica_etiq else "Desconocida",
                "etiqueta_logistica_id": etiqueta.logistica_id,
                "pistoleando_logistica": logistica_pistoleando.nombre if logistica_pistoleando else "Desconocida",
                "pistoleando_logistica_id": payload.logistica_id,
            },
        )

    # Grabar pistoleado
    ahora = datetime.now(UTC)
    etiqueta.pistoleado_at = ahora
    etiqueta.pistoleado_caja = payload.caja
    etiqueta.pistoleado_operador_id = payload.operador_id

    # Registrar actividad
    actividad = OperadorActividad(
        operador_id=payload.operador_id,
        usuario_id=current_user.id,
        tab_key="pistoleado",
        accion="pistoleado",
        detalle={
            "shipping_id": payload.shipping_id,
            "caja": payload.caja,
            "logistica_id": payload.logistica_id,
            "fecha_envio": str(etiqueta.fecha_envio) if etiqueta.fecha_envio else None,
        },
    )
    db.add(actividad)

    db.commit()

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

    # Contar pistoleadas de este operador + logística + fecha (para TTS counter)
    count = (
        db.query(func.count())
        .select_from(EtiquetaEnvio)
        .filter(
            EtiquetaEnvio.pistoleado_operador_id == payload.operador_id,
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
        count=count,
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

    return PistoleadoStatsResponse(
        total_etiquetas=total,
        pistoleadas=pistoleadas,
        pendientes=pendientes,
        porcentaje=porcentaje,
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

    return {"ok": True, "shipping_id": shipping_id, "anulado_por": operador.nombre}
