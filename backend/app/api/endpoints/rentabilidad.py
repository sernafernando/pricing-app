from fastapi import APIRouter, Depends, Query
from sqlalchemy.orm import Session
from sqlalchemy import func, and_, or_
from typing import List, Optional
from datetime import date, datetime
from pydantic import BaseModel

from app.core.database import get_db
from app.models.ml_venta_metrica import MLVentaMetrica
from app.models.offset_ganancia import OffsetGanancia
from app.models.usuario import Usuario
from app.api.deps import get_current_user

router = APIRouter()


class CardRentabilidad(BaseModel):
    """Card de rentabilidad para mostrar en el dashboard"""
    nombre: str
    tipo: str  # marca, categoria, subcategoria, producto
    identificador: Optional[str] = None

    # Métricas
    total_ventas: int
    monto_venta: float
    monto_limpio: float
    costo_total: float
    ganancia: float
    markup_promedio: float

    # Offsets aplicados
    offset_total: float
    ganancia_con_offset: float
    markup_con_offset: float


class RentabilidadResponse(BaseModel):
    cards: List[CardRentabilidad]
    totales: CardRentabilidad
    filtros_aplicados: dict


@router.get("/rentabilidad", response_model=RentabilidadResponse)
async def obtener_rentabilidad(
    fecha_desde: date = Query(..., description="Fecha inicio del período"),
    fecha_hasta: date = Query(..., description="Fecha fin del período"),
    marcas: Optional[str] = Query(None, description="Marcas separadas por coma"),
    categorias: Optional[str] = Query(None, description="Categorías separadas por coma"),
    subcategorias: Optional[str] = Query(None, description="Subcategorías separadas por coma"),
    db: Session = Depends(get_db),
    current_user: Usuario = Depends(get_current_user)
):
    """
    Obtiene métricas de rentabilidad agrupadas según los filtros.
    Los filtros son independientes y se pueden combinar libremente.
    El nivel de agrupación se determina por la cantidad de filtros aplicados.
    """
    # Parsear filtros múltiples
    lista_marcas = [m.strip() for m in marcas.split(',')] if marcas else []
    lista_categorias = [c.strip() for c in categorias.split(',')] if categorias else []
    lista_subcategorias = [s.strip() for s in subcategorias.split(',')] if subcategorias else []

    # Determinar nivel de agrupación basado en cuántos tipos de filtro hay
    filtros_activos = sum([
        1 if lista_marcas else 0,
        1 if lista_categorias else 0,
        1 if lista_subcategorias else 0
    ])

    if lista_subcategorias:
        nivel = "producto"
    elif filtros_activos >= 2:
        nivel = "subcategoria"
    elif filtros_activos == 1:
        nivel = "categoria" if lista_marcas else ("subcategoria" if lista_categorias else "producto")
    else:
        nivel = "marca"

    # Construir query base
    fecha_inicio = datetime.combine(fecha_desde, datetime.min.time())
    fecha_fin = datetime.combine(fecha_hasta, datetime.max.time())

    # Filtros base comunes
    def aplicar_filtros_base(query):
        query = query.filter(
            MLVentaMetrica.fecha_venta >= fecha_inicio,
            MLVentaMetrica.fecha_venta <= fecha_fin
        )
        if lista_marcas:
            query = query.filter(MLVentaMetrica.marca.in_(lista_marcas))
        if lista_categorias:
            query = query.filter(MLVentaMetrica.categoria.in_(lista_categorias))
        if lista_subcategorias:
            query = query.filter(MLVentaMetrica.subcategoria.in_(lista_subcategorias))
        return query

    # Query según nivel de agrupación
    if nivel == "marca":
        query = db.query(
            MLVentaMetrica.marca.label('nombre'),
            MLVentaMetrica.marca.label('identificador'),
            func.count(MLVentaMetrica.id).label('total_ventas'),
            func.sum(MLVentaMetrica.monto_total).label('monto_venta'),
            func.sum(MLVentaMetrica.monto_limpio).label('monto_limpio'),
            func.sum(MLVentaMetrica.costo_total_sin_iva).label('costo_total'),
            func.sum(MLVentaMetrica.ganancia).label('ganancia'),
            func.avg(MLVentaMetrica.markup_porcentaje).label('markup_promedio')
        )
        query = aplicar_filtros_base(query)
        query = query.filter(MLVentaMetrica.marca.isnot(None)).group_by(MLVentaMetrica.marca)

    elif nivel == "categoria":
        query = db.query(
            MLVentaMetrica.categoria.label('nombre'),
            MLVentaMetrica.categoria.label('identificador'),
            func.count(MLVentaMetrica.id).label('total_ventas'),
            func.sum(MLVentaMetrica.monto_total).label('monto_venta'),
            func.sum(MLVentaMetrica.monto_limpio).label('monto_limpio'),
            func.sum(MLVentaMetrica.costo_total_sin_iva).label('costo_total'),
            func.sum(MLVentaMetrica.ganancia).label('ganancia'),
            func.avg(MLVentaMetrica.markup_porcentaje).label('markup_promedio')
        )
        query = aplicar_filtros_base(query)
        query = query.filter(MLVentaMetrica.categoria.isnot(None)).group_by(MLVentaMetrica.categoria)

    elif nivel == "subcategoria":
        query = db.query(
            MLVentaMetrica.subcategoria.label('nombre'),
            MLVentaMetrica.subcategoria.label('identificador'),
            func.count(MLVentaMetrica.id).label('total_ventas'),
            func.sum(MLVentaMetrica.monto_total).label('monto_venta'),
            func.sum(MLVentaMetrica.monto_limpio).label('monto_limpio'),
            func.sum(MLVentaMetrica.costo_total_sin_iva).label('costo_total'),
            func.sum(MLVentaMetrica.ganancia).label('ganancia'),
            func.avg(MLVentaMetrica.markup_porcentaje).label('markup_promedio')
        )
        query = aplicar_filtros_base(query)
        query = query.filter(MLVentaMetrica.subcategoria.isnot(None)).group_by(MLVentaMetrica.subcategoria)

    else:  # producto
        query = db.query(
            func.concat(MLVentaMetrica.codigo, ' - ', MLVentaMetrica.descripcion).label('nombre'),
            MLVentaMetrica.item_id.label('identificador'),
            func.count(MLVentaMetrica.id).label('total_ventas'),
            func.sum(MLVentaMetrica.monto_total).label('monto_venta'),
            func.sum(MLVentaMetrica.monto_limpio).label('monto_limpio'),
            func.sum(MLVentaMetrica.costo_total_sin_iva).label('costo_total'),
            func.sum(MLVentaMetrica.ganancia).label('ganancia'),
            func.avg(MLVentaMetrica.markup_porcentaje).label('markup_promedio')
        )
        query = aplicar_filtros_base(query)
        query = query.group_by(MLVentaMetrica.item_id, MLVentaMetrica.codigo, MLVentaMetrica.descripcion)

    resultados = query.all()

    # Obtener offsets vigentes para el período
    offsets = db.query(OffsetGanancia).filter(
        OffsetGanancia.fecha_desde <= fecha_hasta,
        or_(
            OffsetGanancia.fecha_hasta.is_(None),
            OffsetGanancia.fecha_hasta >= fecha_desde
        )
    ).all()

    # Construir cards
    cards = []
    total_ventas = 0
    total_monto_venta = 0.0
    total_monto_limpio = 0.0
    total_costo = 0.0
    total_ganancia = 0.0
    total_offset = 0.0

    for r in resultados:
        # Calcular offset aplicable
        offset_aplicable = 0.0
        for offset in offsets:
            if nivel == "marca" and offset.marca == r.nombre:
                offset_aplicable += offset.monto
            elif nivel == "categoria" and offset.categoria == r.nombre:
                offset_aplicable += offset.monto
            elif nivel == "subcategoria" and offset.subcategoria_id and str(offset.subcategoria_id) == str(r.identificador):
                offset_aplicable += offset.monto
            elif nivel == "producto" and offset.item_id and str(offset.item_id) == str(r.identificador):
                offset_aplicable += offset.monto

        monto_venta = float(r.monto_venta or 0)
        monto_limpio = float(r.monto_limpio or 0)
        costo_total = float(r.costo_total or 0)
        ganancia = float(r.ganancia or 0)
        markup_promedio = float(r.markup_promedio or 0)

        ganancia_con_offset = ganancia + offset_aplicable
        markup_con_offset = ((ganancia_con_offset / costo_total) * 100) if costo_total > 0 else 0

        cards.append(CardRentabilidad(
            nombre=r.nombre or "Sin nombre",
            tipo=nivel,
            identificador=str(r.identificador) if r.identificador else None,
            total_ventas=r.total_ventas,
            monto_venta=monto_venta,
            monto_limpio=monto_limpio,
            costo_total=costo_total,
            ganancia=ganancia,
            markup_promedio=markup_promedio,
            offset_total=offset_aplicable,
            ganancia_con_offset=ganancia_con_offset,
            markup_con_offset=markup_con_offset
        ))

        # Acumular totales
        total_ventas += r.total_ventas
        total_monto_venta += monto_venta
        total_monto_limpio += monto_limpio
        total_costo += costo_total
        total_ganancia += ganancia
        total_offset += offset_aplicable

    # Ordenar por monto de venta descendente
    cards.sort(key=lambda c: c.monto_venta, reverse=True)

    # Calcular totales
    total_ganancia_con_offset = total_ganancia + total_offset
    total_markup = ((total_ganancia / total_costo) * 100) if total_costo > 0 else 0
    total_markup_con_offset = ((total_ganancia_con_offset / total_costo) * 100) if total_costo > 0 else 0

    totales = CardRentabilidad(
        nombre="TOTAL",
        tipo="total",
        identificador=None,
        total_ventas=total_ventas,
        monto_venta=total_monto_venta,
        monto_limpio=total_monto_limpio,
        costo_total=total_costo,
        ganancia=total_ganancia,
        markup_promedio=total_markup,
        offset_total=total_offset,
        ganancia_con_offset=total_ganancia_con_offset,
        markup_con_offset=total_markup_con_offset
    )

    return RentabilidadResponse(
        cards=cards,
        totales=totales,
        filtros_aplicados={
            "fecha_desde": fecha_desde.isoformat(),
            "fecha_hasta": fecha_hasta.isoformat(),
            "marcas": lista_marcas,
            "categorias": lista_categorias,
            "subcategorias": lista_subcategorias,
            "nivel_agrupacion": nivel
        }
    )


@router.get("/rentabilidad/filtros")
async def obtener_filtros_disponibles(
    fecha_desde: date = Query(...),
    fecha_hasta: date = Query(...),
    marcas: Optional[str] = Query(None),
    categorias: Optional[str] = Query(None),
    subcategorias: Optional[str] = Query(None),
    db: Session = Depends(get_db),
    current_user: Usuario = Depends(get_current_user)
):
    """
    Obtiene los valores disponibles para los filtros basado en los datos del período.
    Los filtros se retroalimentan entre sí (bidireccional).
    """
    lista_marcas = [m.strip() for m in marcas.split(',')] if marcas else []
    lista_categorias = [c.strip() for c in categorias.split(',')] if categorias else []
    lista_subcategorias = [s.strip() for s in subcategorias.split(',')] if subcategorias else []

    fecha_inicio = datetime.combine(fecha_desde, datetime.min.time())
    fecha_fin = datetime.combine(fecha_hasta, datetime.max.time())

    # Marcas disponibles (filtradas por categorías y subcategorías seleccionadas)
    marcas_query = db.query(MLVentaMetrica.marca).filter(
        MLVentaMetrica.fecha_venta >= fecha_inicio,
        MLVentaMetrica.fecha_venta <= fecha_fin,
        MLVentaMetrica.marca.isnot(None)
    )
    if lista_categorias:
        marcas_query = marcas_query.filter(MLVentaMetrica.categoria.in_(lista_categorias))
    if lista_subcategorias:
        marcas_query = marcas_query.filter(MLVentaMetrica.subcategoria.in_(lista_subcategorias))
    marcas_disponibles = marcas_query.distinct().order_by(MLVentaMetrica.marca).all()

    # Categorías disponibles (filtradas por marcas y subcategorías seleccionadas)
    cat_query = db.query(MLVentaMetrica.categoria).filter(
        MLVentaMetrica.fecha_venta >= fecha_inicio,
        MLVentaMetrica.fecha_venta <= fecha_fin,
        MLVentaMetrica.categoria.isnot(None)
    )
    if lista_marcas:
        cat_query = cat_query.filter(MLVentaMetrica.marca.in_(lista_marcas))
    if lista_subcategorias:
        cat_query = cat_query.filter(MLVentaMetrica.subcategoria.in_(lista_subcategorias))
    categorias_disponibles = cat_query.distinct().order_by(MLVentaMetrica.categoria).all()

    # Subcategorías disponibles (filtradas por marcas y categorías seleccionadas)
    subcat_query = db.query(MLVentaMetrica.subcategoria).filter(
        MLVentaMetrica.fecha_venta >= fecha_inicio,
        MLVentaMetrica.fecha_venta <= fecha_fin,
        MLVentaMetrica.subcategoria.isnot(None)
    )
    if lista_marcas:
        subcat_query = subcat_query.filter(MLVentaMetrica.marca.in_(lista_marcas))
    if lista_categorias:
        subcat_query = subcat_query.filter(MLVentaMetrica.categoria.in_(lista_categorias))
    subcategorias_disponibles = subcat_query.distinct().order_by(MLVentaMetrica.subcategoria).all()

    return {
        "marcas": [m[0] for m in marcas_disponibles if m[0]],
        "categorias": [c[0] for c in categorias_disponibles if c[0]],
        "subcategorias": [s[0] for s in subcategorias_disponibles if s[0]]
    }
