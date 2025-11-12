"""
Endpoints para el dashboard de ventas ML con métricas pre-calculadas
"""
from fastapi import APIRouter, Depends, HTTPException, Query
from sqlalchemy.orm import Session
from sqlalchemy import func, and_, desc, extract
from typing import List, Optional
from datetime import datetime, date, timedelta
from decimal import Decimal
from pydantic import BaseModel

from app.core.database import get_db
from app.models.ml_venta_metrica import MLVentaMetrica
from app.api.deps import get_current_user

router = APIRouter()


# Schemas de respuesta
class MetricasGeneralesResponse(BaseModel):
    """Métricas generales del dashboard"""
    total_ventas_ml: Decimal  # Monto total de ventas
    total_limpio: Decimal     # Monto después de comisiones y envío
    total_ganancia: Decimal   # Ganancia total
    total_costo: Decimal      # Costo total
    markup_promedio: Decimal  # Markup promedio ponderado
    cantidad_operaciones: int # Cantidad de operaciones
    cantidad_unidades: int    # Cantidad de unidades vendidas
    total_comisiones: Decimal # Total pagado en comisiones ML
    total_envios: Decimal     # Total pagado en envíos


class VentaPorMarcaResponse(BaseModel):
    """Ventas agrupadas por marca"""
    marca: str
    total_ventas: Decimal
    total_limpio: Decimal
    total_ganancia: Decimal
    markup_promedio: Decimal
    cantidad_operaciones: int
    cantidad_unidades: int


class VentaPorCategoriaResponse(BaseModel):
    """Ventas agrupadas por categoría"""
    categoria: str
    total_ventas: Decimal
    total_limpio: Decimal
    total_ganancia: Decimal
    markup_promedio: Decimal
    cantidad_operaciones: int


class VentaPorLogisticaResponse(BaseModel):
    """Ventas agrupadas por tipo de logística"""
    tipo_logistica: str
    total_ventas: Decimal
    total_envios: Decimal
    cantidad_operaciones: int


class VentaDiariaResponse(BaseModel):
    """Ventas agrupadas por día"""
    fecha: date
    total_ventas: Decimal
    total_limpio: Decimal
    total_ganancia: Decimal
    cantidad_operaciones: int


class TopProductoResponse(BaseModel):
    """Top productos más vendidos"""
    item_id: int
    codigo: Optional[str]
    descripcion: str
    marca: Optional[str]
    total_ventas: Decimal
    total_ganancia: Decimal
    markup_promedio: Decimal
    cantidad_operaciones: int
    cantidad_unidades: int


# Endpoints

@router.get("/dashboard-ml/metricas-generales", response_model=MetricasGeneralesResponse)
async def get_metricas_generales(
    fecha_desde: Optional[str] = Query(None, description="Fecha desde (YYYY-MM-DD)"),
    fecha_hasta: Optional[str] = Query(None, description="Fecha hasta (YYYY-MM-DD)"),
    marca: Optional[str] = Query(None, description="Filtrar por marca"),
    categoria: Optional[str] = Query(None, description="Filtrar por categoría"),
    db: Session = Depends(get_db),
    current_user: dict = Depends(get_current_user)
):
    """
    Obtiene métricas generales del dashboard
    """
    query = db.query(
        func.sum(MLVentaMetrica.monto_total).label('total_ventas_ml'),
        func.sum(MLVentaMetrica.monto_limpio).label('total_limpio'),
        func.sum(MLVentaMetrica.ganancia).label('total_ganancia'),
        func.sum(MLVentaMetrica.costo_total_sin_iva).label('total_costo'),
        func.count(MLVentaMetrica.id).label('cantidad_operaciones'),
        func.sum(MLVentaMetrica.cantidad).label('cantidad_unidades'),
        func.sum(MLVentaMetrica.comision_ml).label('total_comisiones'),
        func.sum(MLVentaMetrica.costo_envio_ml).label('total_envios')
    )

    # Aplicar filtros
    if fecha_desde:
        query = query.filter(MLVentaMetrica.fecha_venta >= datetime.fromisoformat(fecha_desde).date())

    if fecha_hasta:
        query = query.filter(MLVentaMetrica.fecha_venta <= datetime.fromisoformat(fecha_hasta).date())

    if marca:
        query = query.filter(MLVentaMetrica.marca == marca)

    if categoria:
        query = query.filter(MLVentaMetrica.categoria == categoria)

    result = query.first()

    if not result or result.total_ventas_ml is None:
        return MetricasGeneralesResponse(
            total_ventas_ml=Decimal('0'),
            total_limpio=Decimal('0'),
            total_ganancia=Decimal('0'),
            total_costo=Decimal('0'),
            markup_promedio=Decimal('0'),
            cantidad_operaciones=0,
            cantidad_unidades=0,
            total_comisiones=Decimal('0'),
            total_envios=Decimal('0')
        )

    # Calcular markup promedio ponderado
    # markup_promedio = (ganancia_total / costo_total) * 100
    total_costo = result.total_costo or Decimal('0')
    total_ganancia = result.total_ganancia or Decimal('0')

    markup_promedio = Decimal('0')
    if total_costo > 0:
        markup_promedio = (total_ganancia / total_costo) * Decimal('100')

    return MetricasGeneralesResponse(
        total_ventas_ml=result.total_ventas_ml or Decimal('0'),
        total_limpio=result.total_limpio or Decimal('0'),
        total_ganancia=total_ganancia,
        total_costo=total_costo,
        markup_promedio=markup_promedio,
        cantidad_operaciones=result.cantidad_operaciones or 0,
        cantidad_unidades=int(result.cantidad_unidades or 0),
        total_comisiones=result.total_comisiones or Decimal('0'),
        total_envios=result.total_envios or Decimal('0')
    )


@router.get("/dashboard-ml/por-marca", response_model=List[VentaPorMarcaResponse])
async def get_ventas_por_marca(
    fecha_desde: Optional[str] = Query(None),
    fecha_hasta: Optional[str] = Query(None),
    limit: int = Query(20, le=100),
    db: Session = Depends(get_db),
    current_user: dict = Depends(get_current_user)
):
    """
    Obtiene ventas agrupadas por marca
    """
    query = db.query(
        MLVentaMetrica.marca,
        func.sum(MLVentaMetrica.monto_total).label('total_ventas'),
        func.sum(MLVentaMetrica.monto_limpio).label('total_limpio'),
        func.sum(MLVentaMetrica.ganancia).label('total_ganancia'),
        func.sum(MLVentaMetrica.costo_total_sin_iva).label('total_costo'),
        func.count(MLVentaMetrica.id).label('cantidad_operaciones'),
        func.sum(MLVentaMetrica.cantidad).label('cantidad_unidades')
    ).filter(MLVentaMetrica.marca.isnot(None))

    # Aplicar filtros de fecha
    if fecha_desde:
        query = query.filter(MLVentaMetrica.fecha_venta >= datetime.fromisoformat(fecha_desde).date())

    if fecha_hasta:
        query = query.filter(MLVentaMetrica.fecha_venta <= datetime.fromisoformat(fecha_hasta).date())

    resultados = query.group_by(MLVentaMetrica.marca).order_by(desc('total_ventas')).limit(limit).all()

    return [
        VentaPorMarcaResponse(
            marca=r.marca,
            total_ventas=r.total_ventas or Decimal('0'),
            total_limpio=r.total_limpio or Decimal('0'),
            total_ganancia=r.total_ganancia or Decimal('0'),
            markup_promedio=((r.total_ganancia / r.total_costo) * Decimal('100')) if r.total_costo and r.total_costo > 0 else Decimal('0'),
            cantidad_operaciones=r.cantidad_operaciones or 0,
            cantidad_unidades=int(r.cantidad_unidades or 0)
        )
        for r in resultados
    ]


@router.get("/dashboard-ml/por-categoria", response_model=List[VentaPorCategoriaResponse])
async def get_ventas_por_categoria(
    fecha_desde: Optional[str] = Query(None),
    fecha_hasta: Optional[str] = Query(None),
    limit: int = Query(20, le=100),
    db: Session = Depends(get_db),
    current_user: dict = Depends(get_current_user)
):
    """
    Obtiene ventas agrupadas por categoría
    """
    query = db.query(
        MLVentaMetrica.categoria,
        func.sum(MLVentaMetrica.monto_total).label('total_ventas'),
        func.sum(MLVentaMetrica.monto_limpio).label('total_limpio'),
        func.sum(MLVentaMetrica.ganancia).label('total_ganancia'),
        func.sum(MLVentaMetrica.costo_total_sin_iva).label('total_costo'),
        func.count(MLVentaMetrica.id).label('cantidad_operaciones')
    ).filter(MLVentaMetrica.categoria.isnot(None))

    if fecha_desde:
        query = query.filter(MLVentaMetrica.fecha_venta >= datetime.fromisoformat(fecha_desde).date())

    if fecha_hasta:
        query = query.filter(MLVentaMetrica.fecha_venta <= datetime.fromisoformat(fecha_hasta).date())

    resultados = query.group_by(MLVentaMetrica.categoria).order_by(desc('total_ventas')).limit(limit).all()

    return [
        VentaPorCategoriaResponse(
            categoria=r.categoria,
            total_ventas=r.total_ventas or Decimal('0'),
            total_limpio=r.total_limpio or Decimal('0'),
            total_ganancia=r.total_ganancia or Decimal('0'),
            markup_promedio=((r.total_ganancia / r.total_costo) * Decimal('100')) if r.total_costo and r.total_costo > 0 else Decimal('0'),
            cantidad_operaciones=r.cantidad_operaciones or 0
        )
        for r in resultados
    ]


@router.get("/dashboard-ml/por-logistica", response_model=List[VentaPorLogisticaResponse])
async def get_ventas_por_logistica(
    fecha_desde: Optional[str] = Query(None),
    fecha_hasta: Optional[str] = Query(None),
    db: Session = Depends(get_db),
    current_user: dict = Depends(get_current_user)
):
    """
    Obtiene ventas agrupadas por tipo de logística
    """
    query = db.query(
        MLVentaMetrica.tipo_logistica,
        func.sum(MLVentaMetrica.monto_total).label('total_ventas'),
        func.sum(MLVentaMetrica.costo_envio_ml).label('total_envios'),
        func.count(MLVentaMetrica.id).label('cantidad_operaciones')
    ).filter(MLVentaMetrica.tipo_logistica.isnot(None))

    if fecha_desde:
        query = query.filter(MLVentaMetrica.fecha_venta >= datetime.fromisoformat(fecha_desde).date())

    if fecha_hasta:
        query = query.filter(MLVentaMetrica.fecha_venta <= datetime.fromisoformat(fecha_hasta).date())

    resultados = query.group_by(MLVentaMetrica.tipo_logistica).order_by(desc('total_ventas')).all()

    return [
        VentaPorLogisticaResponse(
            tipo_logistica=r.tipo_logistica,
            total_ventas=r.total_ventas or Decimal('0'),
            total_envios=r.total_envios or Decimal('0'),
            cantidad_operaciones=r.cantidad_operaciones or 0
        )
        for r in resultados
    ]


@router.get("/dashboard-ml/por-dia", response_model=List[VentaDiariaResponse])
async def get_ventas_por_dia(
    fecha_desde: Optional[str] = Query(None),
    fecha_hasta: Optional[str] = Query(None),
    db: Session = Depends(get_db),
    current_user: dict = Depends(get_current_user)
):
    """
    Obtiene ventas agrupadas por día
    """
    query = db.query(
        MLVentaMetrica.fecha_venta,
        func.sum(MLVentaMetrica.monto_total).label('total_ventas'),
        func.sum(MLVentaMetrica.monto_limpio).label('total_limpio'),
        func.sum(MLVentaMetrica.ganancia).label('total_ganancia'),
        func.count(MLVentaMetrica.id).label('cantidad_operaciones')
    )

    if fecha_desde:
        query = query.filter(MLVentaMetrica.fecha_venta >= datetime.fromisoformat(fecha_desde).date())

    if fecha_hasta:
        query = query.filter(MLVentaMetrica.fecha_venta <= datetime.fromisoformat(fecha_hasta).date())

    resultados = query.group_by(MLVentaMetrica.fecha_venta).order_by(MLVentaMetrica.fecha_venta).all()

    return [
        VentaDiariaResponse(
            fecha=r.fecha_venta.date() if isinstance(r.fecha_venta, datetime) else r.fecha_venta,
            total_ventas=r.total_ventas or Decimal('0'),
            total_limpio=r.total_limpio or Decimal('0'),
            total_ganancia=r.total_ganancia or Decimal('0'),
            cantidad_operaciones=r.cantidad_operaciones or 0
        )
        for r in resultados
    ]


@router.get("/dashboard-ml/top-productos", response_model=List[TopProductoResponse])
async def get_top_productos(
    fecha_desde: Optional[str] = Query(None),
    fecha_hasta: Optional[str] = Query(None),
    limit: int = Query(10, le=100),
    db: Session = Depends(get_db),
    current_user: dict = Depends(get_current_user)
):
    """
    Obtiene los productos más vendidos
    """
    query = db.query(
        MLVentaMetrica.item_id,
        MLVentaMetrica.codigo,
        MLVentaMetrica.descripcion,
        MLVentaMetrica.marca,
        func.sum(MLVentaMetrica.monto_total).label('total_ventas'),
        func.sum(MLVentaMetrica.ganancia).label('total_ganancia'),
        func.sum(MLVentaMetrica.costo_total_sin_iva).label('total_costo'),
        func.count(MLVentaMetrica.id).label('cantidad_operaciones'),
        func.sum(MLVentaMetrica.cantidad).label('cantidad_unidades')
    ).filter(MLVentaMetrica.item_id.isnot(None))

    if fecha_desde:
        query = query.filter(MLVentaMetrica.fecha_venta >= datetime.fromisoformat(fecha_desde).date())

    if fecha_hasta:
        query = query.filter(MLVentaMetrica.fecha_venta <= datetime.fromisoformat(fecha_hasta).date())

    resultados = query.group_by(
        MLVentaMetrica.item_id,
        MLVentaMetrica.codigo,
        MLVentaMetrica.descripcion,
        MLVentaMetrica.marca
    ).order_by(desc('cantidad_unidades')).limit(limit).all()

    return [
        TopProductoResponse(
            item_id=r.item_id,
            codigo=r.codigo,
            descripcion=r.descripcion,
            marca=r.marca,
            total_ventas=r.total_ventas or Decimal('0'),
            total_ganancia=r.total_ganancia or Decimal('0'),
            markup_promedio=((r.total_ganancia / r.total_costo) * Decimal('100')) if r.total_costo and r.total_costo > 0 else Decimal('0'),
            cantidad_operaciones=r.cantidad_operaciones or 0,
            cantidad_unidades=int(r.cantidad_unidades or 0)
        )
        for r in resultados
    ]


@router.get("/dashboard-ml/marcas-disponibles")
async def get_marcas_disponibles(
    db: Session = Depends(get_db),
    current_user: dict = Depends(get_current_user)
):
    """
    Obtiene lista de marcas disponibles en las métricas
    """
    marcas = db.query(MLVentaMetrica.marca).filter(
        MLVentaMetrica.marca.isnot(None)
    ).distinct().order_by(MLVentaMetrica.marca).all()

    return [m[0] for m in marcas]


@router.get("/dashboard-ml/categorias-disponibles")
async def get_categorias_disponibles(
    db: Session = Depends(get_db),
    current_user: dict = Depends(get_current_user)
):
    """
    Obtiene lista de categorías disponibles en las métricas
    """
    categorias = db.query(MLVentaMetrica.categoria).filter(
        MLVentaMetrica.categoria.isnot(None)
    ).distinct().order_by(MLVentaMetrica.categoria).all()

    return [c[0] for c in categorias]
