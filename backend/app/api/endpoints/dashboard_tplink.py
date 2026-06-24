"""
TP-Link brand-facing dashboard endpoints.

Security guarantees on every endpoint:
1. Permission gate  — requires `dashboard_tplink.ver` (403 otherwise).
2. Store hard-lock  — only store 2645 data is ever returned; client-supplied
   store params are not accepted in the function signatures.
3. PM/marca bypass  — `aplicar_filtro_marcas_pm` is intentionally SKIPPED.
   A brand user has no MarcaPM rows and skipping prevents the __NINGUNA__ branch.
4. Margin masking   — `total_ganancia`, `total_costo`, `markup_porcentaje`,
   `total_comisiones` (and equivalent per-endpoint fields) are Optional; they
   are set to None and excluded from the JSON unless `dashboard_tplink.ver_ganancia`
   is present (`response_model_exclude_none=True` on every route).
5. No offsets       — `total_offset_flex` / `offset_flex` are not in any brand
   response model. No permission can surface them.
"""

from __future__ import annotations

from datetime import date, datetime
from decimal import Decimal
from typing import List, Optional

from fastapi import APIRouter, Depends, Query
from pydantic import BaseModel, ConfigDict
from sqlalchemy import func, desc
from sqlalchemy.orm import Session

from app.api.deps import get_current_user, require_permiso
from app.core.database import get_db
from app.models.ml_venta_metrica import MLVentaMetrica
from app.models.usuario import Usuario
from app.services.permisos_service import PermisosService
from app.api.endpoints.dashboard_ml import aplicar_filtros_comunes
from zoneinfo import ZoneInfo

router = APIRouter()

# TP-Link official store ID — never read from the client request.
TPLINK_OFFICIAL_STORE_ID = 2645

ARGENTINA_TZ = ZoneInfo("America/Argentina/Buenos_Aires")

# ---------------------------------------------------------------------------
# Response models (Pydantic v2)
# All margin fields are Optional so `response_model_exclude_none=True` can
# omit them when the caller lacks `dashboard_tplink.ver_ganancia`.
# No `total_offset_flex` / `offset_flex` field in any model (by construction).
# ---------------------------------------------------------------------------


class MetricasGeneralesTPLinkResponse(BaseModel):
    """Aggregated KPIs for the TP-Link brand dashboard — Resumen tab."""

    total_ventas_ml: Decimal
    total_limpio: Decimal
    cantidad_operaciones: int
    cantidad_unidades: int
    total_envios: Decimal

    # Margin fields — omitted when .ver_ganancia is absent
    total_ganancia: Optional[Decimal] = None
    total_costo: Optional[Decimal] = None
    markup_porcentaje: Optional[Decimal] = None
    total_comisiones: Optional[Decimal] = None

    model_config = ConfigDict(from_attributes=True)


class VentaPorCategoriaTPLinkResponse(BaseModel):
    """Sales by category for the TP-Link brand view."""

    categoria: str
    total_ventas: Decimal
    total_limpio: Decimal
    cantidad_operaciones: int

    # Margin fields — gated
    total_ganancia: Optional[Decimal] = None
    markup_porcentaje: Optional[Decimal] = None

    model_config = ConfigDict(from_attributes=True)


class VentaPorLogisticaTPLinkResponse(BaseModel):
    """Sales by logistics type — no offset fields by construction."""

    tipo_logistica: str
    total_ventas: Decimal
    total_envios: Decimal
    cantidad_operaciones: int

    model_config = ConfigDict(from_attributes=True)


class VentaDiariaTPLinkResponse(BaseModel):
    """Daily sales aggregation."""

    fecha: date
    total_ventas: Decimal
    total_limpio: Decimal
    cantidad_operaciones: int

    # Margin fields — gated
    total_ganancia: Optional[Decimal] = None

    model_config = ConfigDict(from_attributes=True)


class TopProductoTPLinkResponse(BaseModel):
    """Top-selling products for the TP-Link brand view."""

    item_id: int
    codigo: Optional[str] = None
    descripcion: Optional[str] = None
    marca: Optional[str] = None
    total_ventas: Decimal
    cantidad_operaciones: int
    cantidad_unidades: int

    # Margin fields — gated
    total_ganancia: Optional[Decimal] = None
    markup_porcentaje: Optional[Decimal] = None

    model_config = ConfigDict(from_attributes=True)


# ---------------------------------------------------------------------------
# Shared internal helpers
# ---------------------------------------------------------------------------


def _apply_store_lock(query):
    """Filter to TP-Link store 2645 using the direct column on MLVentaMetrica.

    Using `mlp_official_store_id` directly (denormalized column on the metrics
    table) is simpler and testable without joining MercadoLibreItemPublicado.
    This is a stronger lock: the column is on the same table as the data.
    """
    return query.filter(MLVentaMetrica.mlp_official_store_id == TPLINK_OFFICIAL_STORE_ID)


def _has_ganancia(current_user: Usuario, db: Session) -> bool:
    """Return True if the user has the `dashboard_tplink.ver_ganancia` permission."""
    svc = PermisosService(db)
    return svc.tiene_permiso(current_user, "dashboard_tplink.ver_ganancia")


# ---------------------------------------------------------------------------
# Endpoints
# ---------------------------------------------------------------------------


@router.get(
    "/dashboard-tplink/metricas-generales",
    response_model=MetricasGeneralesTPLinkResponse,
    response_model_exclude_none=True,
    dependencies=[Depends(require_permiso("dashboard_tplink.ver"))],
    tags=["dashboard-tplink"],
)
def get_metricas_generales_tplink(
    fecha_desde: Optional[str] = Query(None, description="Date from (YYYY-MM-DD)"),
    fecha_hasta: Optional[str] = Query(None, description="Date to (YYYY-MM-DD)"),
    categorias: Optional[str] = Query(None, description="Filter by categories (comma-separated)"),
    db: Session = Depends(get_db),
    current_user: Usuario = Depends(get_current_user),
) -> MetricasGeneralesTPLinkResponse:
    """
    TP-Link brand KPIs — Resumen tab.

    Store is hard-locked to 2645. Client cannot override it.
    Margin fields are omitted unless caller has `dashboard_tplink.ver_ganancia`.
    No offset fields in response.
    """
    query = db.query(
        func.sum(MLVentaMetrica.monto_total).label("total_ventas_ml"),
        func.sum(MLVentaMetrica.monto_limpio).label("total_limpio"),
        func.sum(MLVentaMetrica.ganancia).label("total_ganancia"),
        func.sum(MLVentaMetrica.costo_total_sin_iva).label("total_costo"),
        func.count(MLVentaMetrica.id).label("cantidad_operaciones"),
        func.sum(MLVentaMetrica.cantidad).label("cantidad_unidades"),
        func.sum(MLVentaMetrica.comision_ml).label("total_comisiones"),
        func.sum(MLVentaMetrica.costo_envio_ml).label("total_envios"),
    )

    # Store lock — never from request params
    query = _apply_store_lock(query)

    # Common filters: date range + categoría only (no marcas, no store params from client)
    query = aplicar_filtros_comunes(query, fecha_desde, fecha_hasta, None, categorias, None, db)

    result = query.first()

    if not result or result.total_ventas_ml is None:
        return MetricasGeneralesTPLinkResponse(
            total_ventas_ml=Decimal("0"),
            total_limpio=Decimal("0"),
            cantidad_operaciones=0,
            cantidad_unidades=0,
            total_envios=Decimal("0"),
        )

    total_costo = Decimal(str(result.total_costo)) if result.total_costo else Decimal("0")
    total_ganancia = Decimal(str(result.total_ganancia)) if result.total_ganancia else Decimal("0")

    markup_porcentaje: Optional[Decimal] = None
    if total_costo > 0:
        markup_porcentaje = round((total_ganancia / total_costo) * Decimal("100"), 2)

    # Build base response without margin fields
    response = MetricasGeneralesTPLinkResponse(
        total_ventas_ml=result.total_ventas_ml or Decimal("0"),
        total_limpio=result.total_limpio or Decimal("0"),
        cantidad_operaciones=result.cantidad_operaciones or 0,
        cantidad_unidades=int(result.cantidad_unidades or 0),
        total_envios=result.total_envios or Decimal("0"),
    )

    # Conditionally include margin fields
    if _has_ganancia(current_user, db):
        response.total_ganancia = total_ganancia
        response.total_costo = total_costo
        response.markup_porcentaje = markup_porcentaje
        response.total_comisiones = result.total_comisiones or Decimal("0")

    return response


@router.get(
    "/dashboard-tplink/por-categoria",
    response_model=List[VentaPorCategoriaTPLinkResponse],
    response_model_exclude_none=True,
    dependencies=[Depends(require_permiso("dashboard_tplink.ver"))],
    tags=["dashboard-tplink"],
)
def get_ventas_por_categoria_tplink(
    fecha_desde: Optional[str] = Query(None),
    fecha_hasta: Optional[str] = Query(None),
    db: Session = Depends(get_db),
    current_user: Usuario = Depends(get_current_user),
) -> List[VentaPorCategoriaTPLinkResponse]:
    """
    Sales by category for the TP-Link brand.
    Store locked to 2645. Margin fields gated by .ver_ganancia.
    """
    query = db.query(
        MLVentaMetrica.categoria,
        func.sum(MLVentaMetrica.monto_total).label("total_ventas"),
        func.sum(MLVentaMetrica.monto_limpio).label("total_limpio"),
        func.sum(MLVentaMetrica.ganancia).label("total_ganancia"),
        func.sum(MLVentaMetrica.costo_total_sin_iva).label("total_costo"),
        func.count(MLVentaMetrica.id).label("cantidad_operaciones"),
    ).filter(MLVentaMetrica.categoria.isnot(None))

    query = _apply_store_lock(query)
    query = aplicar_filtros_comunes(query, fecha_desde, fecha_hasta, None, None, None, db)

    resultados = query.group_by(MLVentaMetrica.categoria).order_by(desc("total_ventas")).all()

    show_ganancia = _has_ganancia(current_user, db)

    return [
        VentaPorCategoriaTPLinkResponse(
            categoria=r.categoria,
            total_ventas=r.total_ventas or Decimal("0"),
            total_limpio=r.total_limpio or Decimal("0"),
            cantidad_operaciones=r.cantidad_operaciones or 0,
            total_ganancia=(r.total_ganancia or Decimal("0")) if show_ganancia else None,
            markup_porcentaje=(
                round((r.total_ganancia / r.total_costo) * Decimal("100"), 2)
                if r.total_costo and r.total_costo > 0
                else Decimal("0")
            )
            if show_ganancia
            else None,
        )
        for r in resultados
    ]


@router.get(
    "/dashboard-tplink/por-logistica",
    response_model=List[VentaPorLogisticaTPLinkResponse],
    response_model_exclude_none=True,
    dependencies=[Depends(require_permiso("dashboard_tplink.ver"))],
    tags=["dashboard-tplink"],
)
def get_ventas_por_logistica_tplink(
    fecha_desde: Optional[str] = Query(None),
    fecha_hasta: Optional[str] = Query(None),
    categorias: Optional[str] = Query(None),
    db: Session = Depends(get_db),
    current_user: Usuario = Depends(get_current_user),
) -> List[VentaPorLogisticaTPLinkResponse]:
    """
    Sales by logistics type for the TP-Link brand.
    Store locked to 2645. No offset fields in response.
    """
    query = db.query(
        MLVentaMetrica.tipo_logistica,
        func.sum(MLVentaMetrica.monto_total).label("total_ventas"),
        func.sum(MLVentaMetrica.costo_envio_ml).label("total_envios"),
        func.count(MLVentaMetrica.id).label("cantidad_operaciones"),
    ).filter(MLVentaMetrica.tipo_logistica.isnot(None))

    query = _apply_store_lock(query)
    query = aplicar_filtros_comunes(query, fecha_desde, fecha_hasta, None, categorias, None, db)

    resultados = query.group_by(MLVentaMetrica.tipo_logistica).order_by(desc("total_ventas")).all()

    return [
        VentaPorLogisticaTPLinkResponse(
            tipo_logistica=r.tipo_logistica,
            total_ventas=r.total_ventas or Decimal("0"),
            total_envios=r.total_envios or Decimal("0"),
            cantidad_operaciones=r.cantidad_operaciones or 0,
        )
        for r in resultados
    ]


@router.get(
    "/dashboard-tplink/por-dia",
    response_model=List[VentaDiariaTPLinkResponse],
    response_model_exclude_none=True,
    dependencies=[Depends(require_permiso("dashboard_tplink.ver"))],
    tags=["dashboard-tplink"],
)
def get_ventas_por_dia_tplink(
    fecha_desde: Optional[str] = Query(None),
    fecha_hasta: Optional[str] = Query(None),
    categorias: Optional[str] = Query(None),
    db: Session = Depends(get_db),
    current_user: Usuario = Depends(get_current_user),
) -> List[VentaDiariaTPLinkResponse]:
    """
    Daily sales aggregation for the TP-Link brand.
    Store locked to 2645. Margin ganancia gated by .ver_ganancia.
    """
    fecha_truncada = func.date(func.timezone("America/Argentina/Buenos_Aires", MLVentaMetrica.fecha_venta))

    query = db.query(
        fecha_truncada.label("fecha"),
        func.sum(MLVentaMetrica.monto_total).label("total_ventas"),
        func.sum(MLVentaMetrica.monto_limpio).label("total_limpio"),
        func.sum(MLVentaMetrica.ganancia).label("total_ganancia"),
        func.count(MLVentaMetrica.id).label("cantidad_operaciones"),
    )

    query = _apply_store_lock(query)
    query = aplicar_filtros_comunes(query, fecha_desde, fecha_hasta, None, categorias, None, db)

    resultados = query.group_by(fecha_truncada).order_by(fecha_truncada).all()

    show_ganancia = _has_ganancia(current_user, db)

    return [
        VentaDiariaTPLinkResponse(
            fecha=r.fecha,
            total_ventas=r.total_ventas or Decimal("0"),
            total_limpio=r.total_limpio or Decimal("0"),
            cantidad_operaciones=r.cantidad_operaciones or 0,
            total_ganancia=(r.total_ganancia or Decimal("0")) if show_ganancia else None,
        )
        for r in resultados
    ]


@router.get(
    "/dashboard-tplink/top-productos",
    response_model=List[TopProductoTPLinkResponse],
    response_model_exclude_none=True,
    dependencies=[Depends(require_permiso("dashboard_tplink.ver"))],
    tags=["dashboard-tplink"],
)
def get_top_productos_tplink(
    fecha_desde: Optional[str] = Query(None),
    fecha_hasta: Optional[str] = Query(None),
    categorias: Optional[str] = Query(None),
    orden: str = Query("unidades", description="Sort by: 'unidades' or 'facturacion'"),
    limit: int = Query(10, le=100),
    db: Session = Depends(get_db),
    current_user: Usuario = Depends(get_current_user),
) -> List[TopProductoTPLinkResponse]:
    """
    Top-selling products for the TP-Link brand.
    Store locked to 2645. Margin fields gated by .ver_ganancia.
    """
    query = db.query(
        MLVentaMetrica.item_id,
        MLVentaMetrica.codigo,
        MLVentaMetrica.descripcion,
        MLVentaMetrica.marca,
        func.sum(MLVentaMetrica.monto_total).label("total_ventas"),
        func.sum(MLVentaMetrica.ganancia).label("total_ganancia"),
        func.sum(MLVentaMetrica.costo_total_sin_iva).label("total_costo"),
        func.count(MLVentaMetrica.id).label("cantidad_operaciones"),
        func.sum(MLVentaMetrica.cantidad).label("cantidad_unidades"),
    ).filter(MLVentaMetrica.item_id.isnot(None))

    query = _apply_store_lock(query)
    query = aplicar_filtros_comunes(query, fecha_desde, fecha_hasta, None, categorias, None, db)

    order_column = "total_ventas" if orden == "facturacion" else "cantidad_unidades"
    resultados = (
        query.group_by(
            MLVentaMetrica.item_id,
            MLVentaMetrica.codigo,
            MLVentaMetrica.descripcion,
            MLVentaMetrica.marca,
        )
        .order_by(desc(order_column))
        .limit(limit)
        .all()
    )

    show_ganancia = _has_ganancia(current_user, db)

    return [
        TopProductoTPLinkResponse(
            item_id=r.item_id,
            codigo=r.codigo,
            descripcion=r.descripcion,
            marca=r.marca,
            total_ventas=r.total_ventas or Decimal("0"),
            cantidad_operaciones=r.cantidad_operaciones or 0,
            cantidad_unidades=int(r.cantidad_unidades or 0),
            total_ganancia=(r.total_ganancia or Decimal("0")) if show_ganancia else None,
            markup_porcentaje=(
                round((r.total_ganancia / r.total_costo) * Decimal("100"), 2)
                if r.total_costo and r.total_costo > 0
                else Decimal("0")
            )
            if show_ganancia
            else None,
        )
        for r in resultados
    ]


@router.get(
    "/dashboard-tplink/categorias-disponibles",
    response_model=List[str],
    dependencies=[Depends(require_permiso("dashboard_tplink.ver"))],
    tags=["dashboard-tplink"],
)
def get_categorias_disponibles_tplink(
    fecha_desde: Optional[str] = Query(None),
    fecha_hasta: Optional[str] = Query(None),
    db: Session = Depends(get_db),
    current_user: Usuario = Depends(get_current_user),
) -> List[str]:
    """
    Available categories for the TP-Link brand store (2645).
    Used to populate the categoría filter dropdown.
    Store locked to 2645.
    """
    query = db.query(MLVentaMetrica.categoria).filter(MLVentaMetrica.categoria.isnot(None))

    query = _apply_store_lock(query)
    query = aplicar_filtros_comunes(query, fecha_desde, fecha_hasta, None, None, None, db)

    categorias = query.distinct().order_by(MLVentaMetrica.categoria).all()
    return [c[0] for c in categorias]


# ---------------------------------------------------------------------------
# Operaciones response model
# ---------------------------------------------------------------------------


class OperacionTPLinkResponse(BaseModel):
    """Per-row operations response for the TP-Link Detalle de Operaciones tab.

    Reads directly from `ml_ventas_metricas` (pre-calculated fields).
    No offset_flex field by construction.
    Margin-related fields (costo_sin_iva, costo_total, comision_porcentaje,
    comision_pesos, markup_porcentaje, ganancia) are Optional — omitted when
    the caller lacks `dashboard_tplink.ver_ganancia`.
    """

    # Operation identifiers
    id_operacion: int
    ml_id: Optional[str] = None
    fecha_venta: datetime

    # Product info
    item_id: Optional[int] = None
    codigo: Optional[str] = None
    descripcion: Optional[str] = None
    categoria: Optional[str] = None
    marca: Optional[str] = None

    # Sale data — always visible
    cantidad: int
    monto_unitario: Decimal
    monto_total: Decimal
    monto_limpio: Decimal
    costo_envio: Decimal
    tipo_logistica: Optional[str] = None
    is_cancelled: bool

    # Margin fields — gated by .ver_ganancia; omitted when absent
    costo_sin_iva: Optional[Decimal] = None
    costo_total: Optional[Decimal] = None
    comision_porcentaje: Optional[Decimal] = None
    comision_pesos: Optional[Decimal] = None
    markup_porcentaje: Optional[Decimal] = None
    ganancia: Optional[Decimal] = None

    model_config = ConfigDict(from_attributes=True)


@router.get(
    "/dashboard-tplink/operaciones",
    response_model=List[OperacionTPLinkResponse],
    response_model_exclude_none=True,
    dependencies=[Depends(require_permiso("dashboard_tplink.ver"))],
    tags=["dashboard-tplink"],
)
def get_operaciones_tplink(
    fecha_desde: Optional[str] = Query(None, description="Date from (YYYY-MM-DD)"),
    fecha_hasta: Optional[str] = Query(None, description="Date to (YYYY-MM-DD)"),
    categorias: Optional[str] = Query(None, description="Filter by categories (comma-separated)"),
    limit: int = Query(1000, le=50000, description="Max results"),
    offset_page: int = Query(0, alias="offset", description="Pagination offset"),
    db: Session = Depends(get_db),
    current_user: Usuario = Depends(get_current_user),
) -> List[OperacionTPLinkResponse]:
    """
    TP-Link Detalle de Operaciones — individual sales rows.

    Reads from ml_ventas_metricas (pre-calculated). Store is hard-locked to 2645.
    Client cannot supply tiendas_oficiales, pm_ids, or marcas — they are not in
    the signature. No offset_flex field. Margin fields omitted unless caller has
    `dashboard_tplink.ver_ganancia`.
    """
    query = db.query(MLVentaMetrica).filter(MLVentaMetrica.is_cancelled.isnot(None))

    # Store lock
    query = _apply_store_lock(query)

    # Date and category filters only (no marca, no store from client)
    query = aplicar_filtros_comunes(query, fecha_desde, fecha_hasta, None, categorias, None, db)

    # Order newest first, paginate
    resultados = query.order_by(MLVentaMetrica.fecha_venta.desc()).offset(offset_page).limit(limit).all()

    show_ganancia = _has_ganancia(current_user, db)

    def _build_row(r: MLVentaMetrica) -> OperacionTPLinkResponse:
        row = OperacionTPLinkResponse(
            id_operacion=r.id_operacion,
            ml_id=r.mla_id,
            fecha_venta=r.fecha_venta,
            item_id=r.item_id,
            codigo=r.codigo,
            descripcion=r.descripcion,
            categoria=r.categoria,
            marca=r.marca,
            cantidad=r.cantidad,
            monto_unitario=r.monto_unitario or Decimal("0"),
            monto_total=r.monto_total or Decimal("0"),
            monto_limpio=r.monto_limpio or Decimal("0"),
            costo_envio=r.costo_envio_ml or Decimal("0"),
            tipo_logistica=r.tipo_logistica,
            is_cancelled=r.is_cancelled if r.is_cancelled is not None else False,
        )
        if show_ganancia:
            row.costo_sin_iva = r.costo_total_sin_iva or Decimal("0")
            row.costo_total = r.costo_total or Decimal("0")
            row.comision_porcentaje = r.porcentaje_comision_ml or Decimal("0")
            row.comision_pesos = r.comision_ml or Decimal("0")
            row.markup_porcentaje = r.markup_porcentaje or Decimal("0")
            row.ganancia = r.ganancia or Decimal("0")
        return row

    return [_build_row(r) for r in resultados]
