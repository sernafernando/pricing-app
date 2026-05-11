"""
Schemas compartidos y helpers reutilizados por los módulos de etiquetas de envío.

Este archivo contiene:
- Pydantic schemas de request/response
- Funciones helper de permisos
- Funciones helper de queries (subqueries, costos, etc.)
- Funciones helper de parseo (QR, ZPL)
- Constantes compartidas
"""

import json
import logging
import re
from datetime import date, datetime
from typing import Any, List, Optional
from uuid import UUID

from fastapi import HTTPException
from pydantic import BaseModel, ConfigDict, Field
from sqlalchemy import and_, case, cast, desc, func, Numeric
from sqlalchemy.orm import Session

from app.models.configuracion import Configuracion
from app.models.etiqueta_envio import EtiquetaEnvio
from app.models.mercadolibre_order_shipping import MercadoLibreOrderShipping
from app.models.sale_order_header import SaleOrderHeader
from app.models.sale_order_header_history import SaleOrderHeaderHistory
from app.models.transporte import Transporte
from app.models.usuario import Usuario
from app.services.permisos_service import verificar_permiso
from app.services.geocoding_service import geocode_address

# Regex para extraer JSONs del QR embebidos en ZPL
QR_JSON_REGEX = re.compile(r'\{"id":"[^}]+\}')


logger = logging.getLogger(__name__)


# ── Permission helpers ───────────────────────────────────────────────


def _check_permiso(db: Session, user: Usuario, codigo: str) -> None:
    """Verifica permiso y lanza 403 si no lo tiene."""
    if not verificar_permiso(db, user, codigo):
        raise HTTPException(
            status_code=403,
            detail=f"No tenés permiso: {codigo}",
        )


def _check_any_permiso(db: Session, user: Usuario, codigos: list[str]) -> None:
    """Verifica que el usuario tenga AL MENOS UNO de los permisos listados."""
    for codigo in codigos:
        if verificar_permiso(db, user, codigo):
            return
    raise HTTPException(
        status_code=403,
        detail=f"No tenés ninguno de estos permisos: {', '.join(codigos)}",
    )


# ── Config helpers ───────────────────────────────────────────────────


def _get_lluvia_config(db: Session) -> tuple[str, float]:
    """Lee la configuración de offset por lluvia desde la tabla configuracion.

    Returns:
        (tipo, valor) — ej: ("fijo", 1800.0) o ("porcentaje", 50.0)
        Si no existe, devuelve ("fijo", 0.0) (sin offset).
    """
    tipo_row = db.query(Configuracion.valor).filter(Configuracion.clave == "lluvia_offset_tipo").first()
    valor_row = db.query(Configuracion.valor).filter(Configuracion.clave == "lluvia_offset_valor").first()
    tipo = tipo_row[0] if tipo_row else "fijo"
    try:
        valor = float(valor_row[0]) if valor_row else 0.0
    except (ValueError, TypeError):
        valor = 0.0
    return tipo, valor


def _build_costo_case(
    costo_turbo_col: Any,
    costo_normal_col: Any,
    lluvia_tipo: str,
    lluvia_valor: float,
) -> Any:
    """Construye la CASE expression de costo_envio con soporte lluvia.

    Lógica:
    1. turbo + lluvia → costo_turbo + offset (fijo o %)
    2. turbo           → costo_turbo (o fallback a normal si no hay turbo)
    3. else            → costo_normal

    El costo_override (manual) se aplica en el COALESCE externo.
    """
    costo_turbo_eff = func.coalesce(costo_turbo_col, costo_normal_col)

    if lluvia_valor > 0:
        if lluvia_tipo == "porcentaje":
            # costo_turbo * (1 + pct/100)
            costo_lluvia = cast(
                costo_turbo_eff * (1 + lluvia_valor / 100),
                Numeric(12, 2),
            )
        else:
            # costo_turbo + monto fijo
            costo_lluvia = cast(
                costo_turbo_eff + lluvia_valor,
                Numeric(12, 2),
            )
    else:
        # Sin offset → lluvia = turbo
        costo_lluvia = cast(costo_turbo_eff, Numeric(12, 2))

    return case(
        (
            and_(EtiquetaEnvio.es_turbo.is_(True), EtiquetaEnvio.es_lluvia.is_(True)),
            costo_lluvia,
        ),
        (
            EtiquetaEnvio.es_turbo.is_(True),
            cast(costo_turbo_eff, Numeric(12, 2)),
        ),
        else_=cast(costo_normal_col, Numeric(12, 2)),
    )


# ── Background task helpers ──────────────────────────────────────────


async def _geocode_envio_manual(
    shipping_id: str,
    street_name: str,
    street_number: str,
    city_name: str,
    transporte_id: Optional[int],
    zip_code: Optional[str] = None,
) -> None:
    """
    Background task: geocodifica un envío manual y guarda lat/lng.

    Lógica:
      1. Si tiene transporte asignado y el transporte YA tiene lat/lng → usar esos.
      2. Si tiene transporte con dirección pero sin lat/lng → geocodificar la
         dirección del transporte, guardar en AMBOS (transporte + etiqueta).
      3. Si no tiene transporte → geocodificar la dirección del cliente.
    """
    from app.core.database import get_background_db

    try:
        with get_background_db() as db:
            etiqueta = db.query(EtiquetaEnvio).filter(EtiquetaEnvio.shipping_id == shipping_id).first()
            if not etiqueta:
                return

            lat, lng = None, None

            # Caso 1 y 2: tiene transporte
            if transporte_id is not None:
                transporte = db.query(Transporte).filter(Transporte.id == transporte_id).first()
                if transporte:
                    if transporte.latitud and transporte.longitud:
                        # Caso 1: transporte ya geocodificado
                        lat, lng = transporte.latitud, transporte.longitud
                    elif transporte.direccion:
                        # Caso 2: geocodificar dirección del transporte
                        ciudad_transp = transporte.localidad or "Buenos Aires"
                        coords = await geocode_address(transporte.direccion, ciudad=ciudad_transp, db=db)
                        if coords:
                            lat, lng = coords
                            transporte.latitud = lat
                            transporte.longitud = lng

            # Caso 3: sin transporte o transporte sin dirección → geocodificar cliente
            if lat is None and street_name:
                direccion_cliente = f"{street_name} {street_number}".strip()
                ciudad = city_name or "Buenos Aires"
                coords = await geocode_address(direccion_cliente, ciudad=ciudad, zip_code=zip_code, db=db)
                if coords:
                    lat, lng = coords

            if lat is not None and lng is not None:
                etiqueta.latitud = lat
                etiqueta.longitud = lng
                # commit is handled by get_background_db() on exit
                logger.info("Geocoding OK para envío manual %s → (%.6f, %.6f)", shipping_id, lat, lng)
            else:
                logger.warning("Geocoding sin resultado para envío manual %s", shipping_id)
    except Exception:
        logger.exception("Error geocodificando envío manual %s", shipping_id)


# ── Query helpers (subqueries) ───────────────────────────────────────


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


def _soh_status_subquery(db: Session, shipping_ids_sub=None):
    """
    Subquery deduplicada: estado ERP por shipping_id (envíos ML).

    Cruza orders_shipping (por mlshippingid) → sale_order_header (por mlo_id).
    Un mismo mlo_id puede tener múltiples filas en SaleOrderHeader
    (una por combinación comp_id/bra_id). Se toma el pedido más reciente
    (mayor soh_cd) con ROW_NUMBER OVER (PARTITION BY mlshippingid ORDER BY soh_cd DESC).

    Si shipping_ids_sub se proporciona, restringe a esos IDs para evitar
    escanear la tabla completa (performance).
    """
    base_q = (
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
    )

    if shipping_ids_sub is not None:
        base_q = base_q.filter(MercadoLibreOrderShipping.mlshippingid.in_(shipping_ids_sub))

    ranked = base_q.subquery()

    return (
        db.query(
            ranked.c.shipping_id_str,
            ranked.c.soh_ssos_id,
        )
        .filter(ranked.c.rn == 1)
        .subquery()
    )


def _manual_soh_status_subquery(db: Session, shipping_ids_sub=None):
    """
    Subquery: estado ERP para envíos manuales (por manual_soh_id + manual_bra_id).

    Los envíos manuales creados desde pedidos tienen manual_soh_id y manual_bra_id
    que referencian directamente a SaleOrderHeader.

    Si shipping_ids_sub se proporciona, restringe a esos IDs para evitar
    escanear la tabla completa (performance).
    """
    base_q = (
        db.query(
            EtiquetaEnvio.shipping_id.label("shipping_id_str"),
            SaleOrderHeader.ssos_id.label("manual_ssos_id"),
            func.row_number()
            .over(
                partition_by=EtiquetaEnvio.shipping_id,
                order_by=desc(SaleOrderHeader.soh_cd),
            )
            .label("rn"),
        )
        .join(
            SaleOrderHeader,
            and_(
                EtiquetaEnvio.manual_soh_id == SaleOrderHeader.soh_id,
                EtiquetaEnvio.manual_bra_id == SaleOrderHeader.bra_id,
            ),
        )
        .filter(
            EtiquetaEnvio.es_manual.is_(True),
            EtiquetaEnvio.manual_soh_id.isnot(None),
            EtiquetaEnvio.manual_bra_id.isnot(None),
        )
    )

    if shipping_ids_sub is not None:
        base_q = base_q.filter(EtiquetaEnvio.shipping_id.in_(shipping_ids_sub))

    ranked = base_q.subquery()

    return (
        db.query(
            ranked.c.shipping_id_str,
            ranked.c.manual_ssos_id,
        )
        .filter(ranked.c.rn == 1)
        .subquery()
    )


def _facturado_ml_subquery(db: Session, shipping_ids_sub=None):
    """
    Subquery: detecta envíos ML cuyo pedido fue facturado.

    Un pedido está facturado cuando:
    1. Ya no existe en sale_order_header (el JOIN principal da NULL)
    2. Existe en sale_order_header_history con ct_transaction IS NOT NULL

    Retorna una fila por shipping_id con is_facturado=True para los que aplican.
    Se usa como fallback cuando soh_sub.soh_ssos_id es NULL.
    """
    base_q = (
        db.query(
            MercadoLibreOrderShipping.mlshippingid.label("shipping_id_str"),
            func.row_number()
            .over(
                partition_by=MercadoLibreOrderShipping.mlshippingid,
                order_by=desc(SaleOrderHeaderHistory.sohh_cd),
            )
            .label("rn"),
        )
        .join(
            SaleOrderHeaderHistory,
            MercadoLibreOrderShipping.mlo_id == SaleOrderHeaderHistory.mlo_id,
        )
        .filter(
            MercadoLibreOrderShipping.mlshippingid.isnot(None),
            MercadoLibreOrderShipping.mlo_id.isnot(None),
            SaleOrderHeaderHistory.ct_transaction.isnot(None),
        )
    )

    if shipping_ids_sub is not None:
        base_q = base_q.filter(MercadoLibreOrderShipping.mlshippingid.in_(shipping_ids_sub))

    ranked = base_q.subquery()

    return db.query(ranked.c.shipping_id_str).filter(ranked.c.rn == 1).subquery()


def _facturado_manual_subquery(db: Session, shipping_ids_sub=None):
    """
    Subquery: detecta envíos manuales cuyo pedido fue facturado.

    Mismo concepto que _facturado_ml_subquery pero para envíos manuales
    que tienen manual_soh_id + manual_bra_id referenciando al pedido.
    """
    base_q = (
        db.query(
            EtiquetaEnvio.shipping_id.label("shipping_id_str"),
            func.row_number()
            .over(
                partition_by=EtiquetaEnvio.shipping_id,
                order_by=desc(SaleOrderHeaderHistory.sohh_cd),
            )
            .label("rn"),
        )
        .join(
            SaleOrderHeaderHistory,
            and_(
                EtiquetaEnvio.manual_soh_id == SaleOrderHeaderHistory.soh_id,
                EtiquetaEnvio.manual_bra_id == SaleOrderHeaderHistory.bra_id,
            ),
        )
        .filter(
            EtiquetaEnvio.es_manual.is_(True),
            EtiquetaEnvio.manual_soh_id.isnot(None),
            EtiquetaEnvio.manual_bra_id.isnot(None),
            SaleOrderHeaderHistory.ct_transaction.isnot(None),
        )
    )

    if shipping_ids_sub is not None:
        base_q = base_q.filter(EtiquetaEnvio.shipping_id.in_(shipping_ids_sub))

    ranked = base_q.subquery()

    return db.query(ranked.c.shipping_id_str).filter(ranked.c.rn == 1).subquery()


def _shipping_dedup_subquery(db: Session, shipping_ids_sub=None):
    """
    Subquery deduplicada: una fila por mlshippingid de MercadoLibreOrderShipping.

    Un mismo mlshippingid puede tener múltiples filas en la tabla
    (una por item/order del envío, con distinto mlm_id).
    Se toma la fila más reciente (mayor mlm_id) con
    ROW_NUMBER OVER (PARTITION BY mlshippingid ORDER BY mlm_id DESC).

    Esto evita que los JOINs multipliquen filas en listado, export y estadísticas.

    Si shipping_ids_sub se proporciona, restringe a esos IDs para evitar
    escanear las 88k+ filas completas (performance: ~50 IDs vs tabla completa).
    """
    base_q = db.query(
        MercadoLibreOrderShipping.mlshippingid.label("mlshippingid"),
        MercadoLibreOrderShipping.mlo_id,
        MercadoLibreOrderShipping.mlreceiver_name,
        MercadoLibreOrderShipping.mlstreet_name,
        MercadoLibreOrderShipping.mlstreet_number,
        MercadoLibreOrderShipping.mlzip_code,
        MercadoLibreOrderShipping.mlcity_name,
        MercadoLibreOrderShipping.mlstatus,
        MercadoLibreOrderShipping.mlsubstatus,
        MercadoLibreOrderShipping.ml_estimated_delivery_time_date,
        func.row_number()
        .over(
            partition_by=MercadoLibreOrderShipping.mlshippingid,
            order_by=desc(MercadoLibreOrderShipping.mlm_id),
        )
        .label("rn"),
    ).filter(MercadoLibreOrderShipping.mlshippingid.isnot(None))

    if shipping_ids_sub is not None:
        base_q = base_q.filter(MercadoLibreOrderShipping.mlshippingid.in_(shipping_ids_sub))

    ranked = base_q.subquery()

    return (
        db.query(
            ranked.c.mlshippingid,
            ranked.c.mlo_id,
            ranked.c.mlreceiver_name,
            ranked.c.mlstreet_name,
            ranked.c.mlstreet_number,
            ranked.c.mlzip_code,
            ranked.c.mlcity_name,
            ranked.c.mlstatus,
            ranked.c.mlsubstatus,
            ranked.c.ml_estimated_delivery_time_date,
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
    upload_batch_id: Optional[UUID] = None,
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
        upload_batch_id=upload_batch_id,
    )
    db.add(etiqueta)
    return True


# ── Schemas ──────────────────────────────────────────────────────────


class UploadResultResponse(BaseModel):
    """Resultado de la carga de etiquetas desde archivo."""

    total: int
    nuevas: int
    duplicadas: int
    errores: int = 0
    detalle_errores: List[str] = []
    upload_batch_id: Optional[UUID] = None


class ManualScanRequest(BaseModel):
    """Payload del escaneo manual con pistola."""

    json_data: str = Field(
        description='JSON raw del QR, ej: {"id":"46458064834","sender_id":413658225,...}',
    )
    fecha_envio: Optional[date] = Field(
        None,
        description="Fecha de envío para esta etiqueta. Default: hoy.",
    )


class LoteEnvioResponse(BaseModel):
    """Resumen de un lote de carga de flex (un POST /etiquetas-envio/upload)."""

    upload_batch_id: UUID
    primer_carga_at: datetime
    total: int
    nombre_archivo: Optional[str] = None
    fecha_envio: date


class CambiarFechaMasivoRequest(BaseModel):
    """Payload para cambio masivo de fecha de envío."""

    shipping_ids: List[str] = Field(min_length=1)
    fecha_envio: date


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
    upload_batch_id: Optional[UUID] = None
    fecha_envio: date
    logistica_id: Optional[int] = None
    logistica_nombre: Optional[str] = None
    logistica_color: Optional[str] = None

    # Order ID de MercadoLibre (para link a detalle de venta en ML)
    ml_order_id: Optional[str] = None

    # Buyer nickname de MercadoLibre (ej: GUSY2007)
    mluser_nickname: Optional[str] = None

    # Datos de ML shipping
    mlreceiver_name: Optional[str] = None
    mlstreet_name: Optional[str] = None
    mlstreet_number: Optional[str] = None
    mlzip_code: Optional[str] = None
    mlcity_name: Optional[str] = None
    mlstatus: Optional[str] = None
    mlsubstatus: Optional[str] = None

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

    # Envío manual (sin ML)
    es_manual: bool = False
    manual_bra_id: Optional[int] = None
    manual_soh_id: Optional[int] = None
    manual_cust_id: Optional[int] = None
    manual_comment: Optional[str] = None
    manual_phone: Optional[str] = None

    # Outlet (título de item contiene "outlet")
    es_outlet: bool = False

    # Turbo (mlshipping_method_id == "515282")
    es_turbo: bool = False

    # Fechas de entrega turbo (para detección de demora)
    ml_date_delivered: Optional[str] = None
    ml_estimated_delivery_time_date: Optional[str] = None

    # Lluvia — recargo extra sobre turbo
    es_lluvia: bool = False

    # Flag de envío (mal pasado, cancelado, duplicado, otro)
    flag_envio: Optional[str] = None
    flag_envio_motivo: Optional[str] = None
    flag_envio_at: Optional[str] = None
    flag_envio_usuario_nombre: Optional[str] = None

    # Retornado (paquete devuelto físicamente a la oficina)
    retornado: Optional[bool] = None
    retornado_at: Optional[str] = None
    retornado_usuario_nombre: Optional[str] = None

    # Creado por usuario del sistema (cuando viene de Pedidos Pendientes)
    creado_por_usuario_nombre: Optional[str] = None

    # Transporte interprovincial
    transporte_id: Optional[int] = None
    transporte_nombre: Optional[str] = None
    transporte_color: Optional[str] = None
    transporte_direccion: Optional[str] = None
    transporte_cp: Optional[str] = None
    transporte_localidad: Optional[str] = None
    transporte_telefono: Optional[str] = None
    transporte_horario: Optional[str] = None

    model_config = ConfigDict(from_attributes=True)


class EtiquetaPaginatedResponse(BaseModel):
    """Respuesta paginada del listado de etiquetas.

    Se devuelve cuando el cliente envía ?page=N explícitamente.
    Si no se envía page, el endpoint devuelve List[EtiquetaEnvioResponse]
    directamente (backwards compatible).
    """

    items: List[EtiquetaEnvioResponse]
    total: int
    page: int
    page_size: int


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
    flagged: int = 0
    retornados: int = 0


class EstadisticaDiaItem(BaseModel):
    """Estadísticas de un día individual para la vista calendario."""

    fecha: date
    total: int = 0
    flex: int = 0
    manuales: int = 0
    por_cordon: dict[str, int] = {}
    sin_cordon: int = 0
    con_logistica: int = 0
    sin_logistica: int = 0
    enviados: int = 0
    no_entregados: int = 0


class EstadisticasPorDiaResponse(BaseModel):
    """Respuesta del endpoint de estadísticas agrupadas por día."""

    dias: List[EstadisticaDiaItem]


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


class CrearEnvioManualRequest(BaseModel):
    """Payload para crear un envío manual (sin MercadoLibre)."""

    fecha_envio: date
    receiver_name: str = Field(max_length=500, description="Nombre del destinatario")
    street_name: str = Field(max_length=500, description="Calle")
    street_number: str = Field(max_length=50, description="Número")
    zip_code: str = Field(max_length=50, description="Código postal")
    city_name: str = Field(max_length=500, description="Ciudad / Localidad")
    status: str = Field(
        description="Estado del envío: ready_to_ship, shipped, delivered",
        pattern="^(ready_to_ship|shipped|delivered)$",
    )
    cust_id: Optional[int] = Field(
        None, description="ID de cliente del ERP. Se resuelve automáticamente si se envía soh_id + bra_id."
    )
    bra_id: Optional[int] = Field(None, description="Sucursal (tb_branch.bra_id)")
    soh_id: Optional[int] = Field(None, description="N° pedido ERP (soh_id de SaleOrderHeader)")
    logistica_id: Optional[int] = Field(None, description="Logística asignada")
    transporte_id: Optional[int] = Field(None, description="Transporte interprovincial asignado")
    comment: Optional[str] = Field(None, max_length=1000, description="Observaciones")
    phone: Optional[str] = Field(None, max_length=100, description="Teléfono del destinatario")
    operador_id: int = Field(description="Operador autenticado con PIN")


class CrearEnvioManualResponse(BaseModel):
    """Resultado de la creación de un envío manual."""

    ok: bool = True
    shipping_id: str
    cordon: Optional[str] = None
    mensaje: str


class CrearDesdePedidoRequest(BaseModel):
    """Payload para crear un envío flex desde la tab Pedidos Pendientes.

    Si se envían soh_id + bra_id, se resuelve el cust_id automáticamente.
    Si no se envían, se crea un envío manual puro (sin pedido asociado).
    """

    fecha_envio: date
    soh_id: Optional[int] = Field(None, description="N° pedido ERP (opcional)")
    bra_id: Optional[int] = Field(None, description="Sucursal (opcional)")
    receiver_name: str = Field(max_length=500, description="Nombre del destinatario")
    street_name: str = Field(max_length=500, description="Dirección completa")
    street_number: str = Field(max_length=50, default="S/N", description="Número")
    zip_code: str = Field(max_length=50, description="Código postal")
    city_name: str = Field(max_length=500, description="Ciudad / Localidad")
    comment: Optional[str] = Field(None, max_length=1000, description="Observaciones")
    phone: Optional[str] = Field(None, max_length=100, description="Teléfono del destinatario")
    logistica_id: Optional[int] = Field(None, description="Logística asignada")
    transporte_id: Optional[int] = Field(None, description="Transporte interprovincial asignado")
    cust_id: Optional[int] = Field(None, description="ID cliente ERP (si no hay pedido)")
    status: Optional[str] = Field(
        None,
        description="Estado del envío (default: ready_to_ship)",
        pattern="^(ready_to_ship|shipped|delivered)$",
    )


class AsignarMasivoRequest(BaseModel):
    """Payload para asignación masiva de logística."""

    shipping_ids: List[str] = Field(min_length=1)
    logistica_id: int


class AsignarTransporteMasivoRequest(BaseModel):
    """Payload para asignación masiva de transporte."""

    shipping_ids: List[str] = Field(min_length=1)
    transporte_id: Optional[int] = Field(None, description="ID del transporte (None para desasignar)")


class ShippingIdsRequest(BaseModel):
    """Payload genérico con lista de shipping_ids."""

    shipping_ids: List[str] = Field(min_length=1)


FLAG_ENVIO_VALIDOS = {"mal_pasado", "envio_cancelado", "duplicado", "otro"}


class FlagEnvioRequest(BaseModel):
    """Payload para flaggear un envío."""

    flag_envio: Optional[str] = Field(
        None,
        description="Tipo de flag: mal_pasado, envio_cancelado, duplicado, otro. None para quitar flag.",
    )
    motivo: Optional[str] = Field(
        None,
        max_length=500,
        description="Observación libre (se muestra como tooltip en el badge)",
    )


class FlagEnvioMasivoRequest(BaseModel):
    """Payload para flaggear múltiples envíos."""

    shipping_ids: List[str] = Field(min_length=1)
    flag_envio: Optional[str] = Field(
        None,
        description="Tipo de flag: mal_pasado, envio_cancelado, duplicado, otro. None para quitar flag.",
    )
    motivo: Optional[str] = Field(
        None,
        max_length=500,
        description="Observación libre",
    )


# ── Schemas Retornado ────────────────────────────────────────────────


class RetornadoMasivoRequest(BaseModel):
    """Payload para marcar o desmarcar envíos como retornados."""

    shipping_ids: List[str] = Field(min_length=1)
    retornado: bool = Field(
        description="True para marcar como retornado, False para desmarcar",
    )


# ── Schemas Pistoleado ───────────────────────────────────────────────


class PistolearRequest(BaseModel):
    """Payload del pistoleado: escaneo de QR de etiqueta en depósito."""

    shipping_id: str = Field(description="shipping_id extraído del QR de la etiqueta")
    caja: str = Field(max_length=50, description="Contenedor activo (CAJA 1, SUELTOS 1, etc.)")
    logistica_id: int = Field(description="Logística que el operador está pistoleando")
    operador_id: int = Field(description="Operador autenticado con PIN")
    bulto: Optional[int] = Field(None, description="N° de bulto escaneado (del QR). None = bulto único.")
    total_bultos: Optional[int] = Field(None, description="Total bultos del envío (del QR)")
    forzar_asignacion: bool = Field(
        False, description="Si True, asigna la logística aunque no tenga pistoleado_asigna (doble escaneo)"
    )


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
    bulto: Optional[int] = None
    total_bultos: Optional[int] = None
    bultos_pistoleados: int = Field(0, description="Cantidad de bultos pistoleados hasta ahora")
    count: int = Field(description="Total pistoleadas en esta sesión (fecha + logística + operador)")
    estado_erp: Optional[str] = Field(None, description="Nombre del estado ERP del pedido (ssos_name)")
    logistica_asignada: bool = Field(
        False,
        description="True si la logística fue asignada por el pistoleado (modo pistoleado_asigna)",
    )

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
    en_preparacion: int = Field(0, description="Pistoleadas cuyo pedido ERP está En Preparación")
    por_caja: dict[str, int]
    por_operador: dict[str, int]


class BorrarEtiquetasRequest(BaseModel):
    """Payload para borrar etiquetas con auditoría."""

    shipping_ids: List[str] = Field(min_length=1)
    comment: Optional[str] = Field(None, max_length=500, description="Motivo del borrado")


# ── Schemas Check Updates ────────────────────────────────────────────


class CheckUpdatesResponse(BaseModel):
    """Respuesta ligera para polling: count + timestamp del último cambio."""

    count: int = Field(description="Total de etiquetas que matchean los filtros base")
    last_updated: Optional[str] = Field(None, description="Timestamp ISO del último updated_at")

    model_config = ConfigDict(from_attributes=True)


# ── Schemas Re-enrichment ────────────────────────────────────────────


class ReEnriquecerRequest(BaseModel):
    """Body para re-enriquecer etiquetas."""

    fecha_desde: Optional[date] = None
    fecha_hasta: Optional[date] = None
    shipping_ids: Optional[List[str]] = None


# ── Schemas Geocodificación ──────────────────────────────────────────


class GeocodificarRequest(BaseModel):
    """IDs de etiquetas a geocodificar."""

    shipping_ids: List[str]


class GeocodificarResponse(BaseModel):
    """Resultado de geocodificación masiva."""

    total: int
    geocodificados: int
    ya_tenian: int
    sin_resultado: int
    errores: int


class GeocodificarIndividualResponse(BaseModel):
    """Resultado de geocodificación individual."""

    shipping_id: str
    latitud: Optional[float] = None
    longitud: Optional[float] = None
    direccion_usada: Optional[str] = None
    ok: bool
    mensaje: str


# ── Schemas Export Manuales ──────────────────────────────────────────


class ExportManualEnvio(BaseModel):
    """Un envío manual con datos editados para exportar."""

    numero_tracking: str = ""
    fecha_venta: str = ""
    valor_declarado: str = ""
    peso_declarado: str = ""
    destinatario: str = ""
    telefono: str = ""
    direccion: str = ""
    localidad: str = ""
    codigo_postal: str = ""
    observaciones: str = ""
    total_a_cobrar: str = ""
    logistica_inversa: str = ""

    model_config = ConfigDict(from_attributes=True)


class ExportManualesRequest(BaseModel):
    """Request body para exportar envíos manuales."""

    envios: List[ExportManualEnvio]


# ── Constantes Export ────────────────────────────────────────────────

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
    "turbo": "Turbo",
    "lluvia": "Lluvia",
    "flag_envio": "Flag",
    "flag_envio_motivo": "Motivo Flag",
}

EXPORT_MANUALES_COLUMNS = [
    ("numero_tracking", "Numero de tracking"),
    ("fecha_venta", "Fecha de venta"),
    ("valor_declarado", "Valor declarado"),
    ("peso_declarado", "Peso declarado"),
    ("destinatario", "Destinatario"),
    ("telefono", "Teléfono de contacto"),
    ("direccion", "Dirección"),
    ("localidad", "Localidad"),
    ("codigo_postal", "Código postal"),
    ("observaciones", "Observaciones"),
    ("total_a_cobrar", "4 Total a cobrar"),
    ("logistica_inversa", "1 Logistica Inversa"),
]
