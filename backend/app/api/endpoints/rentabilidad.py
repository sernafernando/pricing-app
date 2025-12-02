from fastapi import APIRouter, Depends, Query
from sqlalchemy.orm import Session
from sqlalchemy import func, and_, or_, case
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
    identificador: Optional[str] = None  # Para subcategoria_id o item_id

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
    subcategorias: Optional[str] = Query(None, description="IDs de subcategorías separados por coma"),
    db: Session = Depends(get_db),
    current_user: Usuario = Depends(get_current_user)
):
    """
    Obtiene métricas de rentabilidad agrupadas según los filtros.
    Sin filtros: agrupa por marca
    Con marca: agrupa por categoría
    Con marca+categoría: agrupa por subcategoría
    Con marca+categoría+subcategoría: agrupa por producto
    """
    # Parsear filtros múltiples
    lista_marcas = [m.strip() for m in marcas.split(',')] if marcas else []
    lista_categorias = [c.strip() for c in categorias.split(',')] if categorias else []
    lista_subcategorias = [int(s.strip()) for s in subcategorias.split(',')] if subcategorias else []

    # Determinar nivel de agrupación
    if lista_subcategorias:
        nivel = "producto"
        group_by_field = MLVentaMetrica.item_id
        label_field = func.concat(MLVentaMetrica.codigo, ' - ', MLVentaMetrica.descripcion)
    elif lista_categorias:
        nivel = "subcategoria"
        group_by_field = MLVentaMetrica.subcategoria
        label_field = MLVentaMetrica.subcategoria
    elif lista_marcas:
        nivel = "categoria"
        group_by_field = MLVentaMetrica.categoria
        label_field = MLVentaMetrica.categoria
    else:
        nivel = "marca"
        group_by_field = MLVentaMetrica.marca
        label_field = MLVentaMetrica.marca

    # Query base con filtros de fecha
    query = db.query(
        label_field.label('nombre'),
        group_by_field.label('identificador'),
        func.count(MLVentaMetrica.id).label('total_ventas'),
        func.sum(MLVentaMetrica.monto_total).label('monto_venta'),
        func.sum(MLVentaMetrica.monto_limpio).label('monto_limpio'),
        func.sum(MLVentaMetrica.costo_total_sin_iva).label('costo_total'),
        func.sum(MLVentaMetrica.ganancia).label('ganancia'),
        func.avg(MLVentaMetrica.markup_porcentaje).label('markup_promedio'),
        # Campos adicionales para offsets
        MLVentaMetrica.marca,
        MLVentaMetrica.categoria,
        MLVentaMetrica.subcategoria,
        MLVentaMetrica.item_id
    ).filter(
        MLVentaMetrica.fecha_venta >= datetime.combine(fecha_desde, datetime.min.time()),
        MLVentaMetrica.fecha_venta <= datetime.combine(fecha_hasta, datetime.max.time())
    )

    # Aplicar filtros
    if lista_marcas:
        query = query.filter(MLVentaMetrica.marca.in_(lista_marcas))
    if lista_categorias:
        query = query.filter(MLVentaMetrica.categoria.in_(lista_categorias))
    if lista_subcategorias:
        # Necesitamos obtener el nombre de subcategoría desde algún lugar
        # Por ahora filtramos por el campo subcategoria que es string
        pass  # TODO: implementar filtro por subcategoria_id

    # Agrupar
    if nivel == "producto":
        query = query.group_by(
            MLVentaMetrica.item_id,
            MLVentaMetrica.codigo,
            MLVentaMetrica.descripcion,
            MLVentaMetrica.marca,
            MLVentaMetrica.categoria,
            MLVentaMetrica.subcategoria
        )
    else:
        query = query.group_by(
            group_by_field,
            MLVentaMetrica.marca,
            MLVentaMetrica.categoria,
            MLVentaMetrica.subcategoria,
            MLVentaMetrica.item_id
        )

    # Ejecutar query agrupada correctamente
    # Rehacer la query para agrupar correctamente
    if nivel == "producto":
        resultados = db.query(
            func.concat(MLVentaMetrica.codigo, ' - ', MLVentaMetrica.descripcion).label('nombre'),
            MLVentaMetrica.item_id.label('identificador'),
            func.count(MLVentaMetrica.id).label('total_ventas'),
            func.sum(MLVentaMetrica.monto_total).label('monto_venta'),
            func.sum(MLVentaMetrica.monto_limpio).label('monto_limpio'),
            func.sum(MLVentaMetrica.costo_total_sin_iva).label('costo_total'),
            func.sum(MLVentaMetrica.ganancia).label('ganancia'),
            func.avg(MLVentaMetrica.markup_porcentaje).label('markup_promedio'),
            MLVentaMetrica.marca.label('marca_grupo'),
            MLVentaMetrica.categoria.label('categoria_grupo'),
            MLVentaMetrica.subcategoria.label('subcategoria_grupo')
        ).filter(
            MLVentaMetrica.fecha_venta >= datetime.combine(fecha_desde, datetime.min.time()),
            MLVentaMetrica.fecha_venta <= datetime.combine(fecha_hasta, datetime.max.time())
        )
        if lista_marcas:
            resultados = resultados.filter(MLVentaMetrica.marca.in_(lista_marcas))
        if lista_categorias:
            resultados = resultados.filter(MLVentaMetrica.categoria.in_(lista_categorias))
        resultados = resultados.group_by(
            MLVentaMetrica.item_id,
            MLVentaMetrica.codigo,
            MLVentaMetrica.descripcion,
            MLVentaMetrica.marca,
            MLVentaMetrica.categoria,
            MLVentaMetrica.subcategoria
        ).all()
    elif nivel == "subcategoria":
        resultados = db.query(
            MLVentaMetrica.subcategoria.label('nombre'),
            MLVentaMetrica.subcategoria.label('identificador'),
            func.count(MLVentaMetrica.id).label('total_ventas'),
            func.sum(MLVentaMetrica.monto_total).label('monto_venta'),
            func.sum(MLVentaMetrica.monto_limpio).label('monto_limpio'),
            func.sum(MLVentaMetrica.costo_total_sin_iva).label('costo_total'),
            func.sum(MLVentaMetrica.ganancia).label('ganancia'),
            func.avg(MLVentaMetrica.markup_porcentaje).label('markup_promedio'),
            MLVentaMetrica.marca.label('marca_grupo'),
            MLVentaMetrica.categoria.label('categoria_grupo'),
            MLVentaMetrica.subcategoria.label('subcategoria_grupo')
        ).filter(
            MLVentaMetrica.fecha_venta >= datetime.combine(fecha_desde, datetime.min.time()),
            MLVentaMetrica.fecha_venta <= datetime.combine(fecha_hasta, datetime.max.time())
        )
        if lista_marcas:
            resultados = resultados.filter(MLVentaMetrica.marca.in_(lista_marcas))
        if lista_categorias:
            resultados = resultados.filter(MLVentaMetrica.categoria.in_(lista_categorias))
        resultados = resultados.group_by(
            MLVentaMetrica.subcategoria,
            MLVentaMetrica.marca,
            MLVentaMetrica.categoria
        ).all()
    elif nivel == "categoria":
        resultados = db.query(
            MLVentaMetrica.categoria.label('nombre'),
            MLVentaMetrica.categoria.label('identificador'),
            func.count(MLVentaMetrica.id).label('total_ventas'),
            func.sum(MLVentaMetrica.monto_total).label('monto_venta'),
            func.sum(MLVentaMetrica.monto_limpio).label('monto_limpio'),
            func.sum(MLVentaMetrica.costo_total_sin_iva).label('costo_total'),
            func.sum(MLVentaMetrica.ganancia).label('ganancia'),
            func.avg(MLVentaMetrica.markup_porcentaje).label('markup_promedio'),
            MLVentaMetrica.marca.label('marca_grupo'),
            MLVentaMetrica.categoria.label('categoria_grupo'),
            func.literal(None).label('subcategoria_grupo')
        ).filter(
            MLVentaMetrica.fecha_venta >= datetime.combine(fecha_desde, datetime.min.time()),
            MLVentaMetrica.fecha_venta <= datetime.combine(fecha_hasta, datetime.max.time())
        )
        if lista_marcas:
            resultados = resultados.filter(MLVentaMetrica.marca.in_(lista_marcas))
        resultados = resultados.group_by(
            MLVentaMetrica.categoria,
            MLVentaMetrica.marca
        ).all()
    else:  # marca
        resultados = db.query(
            MLVentaMetrica.marca.label('nombre'),
            MLVentaMetrica.marca.label('identificador'),
            func.count(MLVentaMetrica.id).label('total_ventas'),
            func.sum(MLVentaMetrica.monto_total).label('monto_venta'),
            func.sum(MLVentaMetrica.monto_limpio).label('monto_limpio'),
            func.sum(MLVentaMetrica.costo_total_sin_iva).label('costo_total'),
            func.sum(MLVentaMetrica.ganancia).label('ganancia'),
            func.avg(MLVentaMetrica.markup_porcentaje).label('markup_promedio'),
            MLVentaMetrica.marca.label('marca_grupo'),
            func.literal(None).label('categoria_grupo'),
            func.literal(None).label('subcategoria_grupo')
        ).filter(
            MLVentaMetrica.fecha_venta >= datetime.combine(fecha_desde, datetime.min.time()),
            MLVentaMetrica.fecha_venta <= datetime.combine(fecha_hasta, datetime.max.time())
        ).group_by(MLVentaMetrica.marca).all()

    # Obtener offsets vigentes para el período
    offsets = db.query(OffsetGanancia).filter(
        OffsetGanancia.fecha_desde <= fecha_hasta,
        or_(
            OffsetGanancia.fecha_hasta.is_(None),
            OffsetGanancia.fecha_hasta >= fecha_desde
        )
    ).all()

    # Construir cards con offsets aplicados
    cards = []
    total_ventas = 0
    total_monto_venta = 0.0
    total_monto_limpio = 0.0
    total_costo = 0.0
    total_ganancia = 0.0
    total_offset = 0.0

    for r in resultados:
        # Calcular offset aplicable a este grupo
        offset_aplicable = 0.0
        for offset in offsets:
            aplica = False

            # Verificar si el offset aplica a este resultado
            if offset.item_id and nivel == "producto":
                if str(offset.item_id) == str(r.identificador):
                    aplica = True
            elif offset.subcategoria_id and nivel in ["subcategoria", "producto"]:
                # Necesitaríamos el subcategoria_id del resultado
                pass
            elif offset.categoria and r.categoria_grupo:
                if offset.categoria == r.categoria_grupo:
                    aplica = True
            elif offset.marca and r.marca_grupo:
                if offset.marca == r.marca_grupo:
                    aplica = True

            if aplica:
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
    db: Session = Depends(get_db),
    current_user: Usuario = Depends(get_current_user)
):
    """
    Obtiene los valores disponibles para los filtros basado en los datos del período
    """
    lista_marcas = [m.strip() for m in marcas.split(',')] if marcas else []
    lista_categorias = [c.strip() for c in categorias.split(',')] if categorias else []

    base_query = db.query(MLVentaMetrica).filter(
        MLVentaMetrica.fecha_venta >= datetime.combine(fecha_desde, datetime.min.time()),
        MLVentaMetrica.fecha_venta <= datetime.combine(fecha_hasta, datetime.max.time())
    )

    # Marcas disponibles
    marcas_disponibles = db.query(MLVentaMetrica.marca).filter(
        MLVentaMetrica.fecha_venta >= datetime.combine(fecha_desde, datetime.min.time()),
        MLVentaMetrica.fecha_venta <= datetime.combine(fecha_hasta, datetime.max.time()),
        MLVentaMetrica.marca.isnot(None)
    ).distinct().order_by(MLVentaMetrica.marca).all()

    # Categorías disponibles (filtradas por marca si se seleccionó)
    cat_query = db.query(MLVentaMetrica.categoria).filter(
        MLVentaMetrica.fecha_venta >= datetime.combine(fecha_desde, datetime.min.time()),
        MLVentaMetrica.fecha_venta <= datetime.combine(fecha_hasta, datetime.max.time()),
        MLVentaMetrica.categoria.isnot(None)
    )
    if lista_marcas:
        cat_query = cat_query.filter(MLVentaMetrica.marca.in_(lista_marcas))
    categorias_disponibles = cat_query.distinct().order_by(MLVentaMetrica.categoria).all()

    # Subcategorías disponibles (filtradas por marca y categoría si se seleccionaron)
    subcat_query = db.query(MLVentaMetrica.subcategoria).filter(
        MLVentaMetrica.fecha_venta >= datetime.combine(fecha_desde, datetime.min.time()),
        MLVentaMetrica.fecha_venta <= datetime.combine(fecha_hasta, datetime.max.time()),
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
