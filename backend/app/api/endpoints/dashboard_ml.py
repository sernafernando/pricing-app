"""
Endpoints para el dashboard de ventas ML con métricas pre-calculadas
"""
from fastapi import APIRouter, Depends, Query
from sqlalchemy.orm import Session
from sqlalchemy import func, desc, tuple_
from typing import List, Optional
from datetime import datetime, date, timedelta
from decimal import Decimal
from pydantic import BaseModel
from zoneinfo import ZoneInfo

from app.core.database import get_db
from app.models.ml_venta_metrica import MLVentaMetrica
from app.models.usuario import Usuario, RolUsuario
from app.models.marca_pm import MarcaPM
from app.api.deps import get_current_user

# Timezone de Argentina
ARGENTINA_TZ = ZoneInfo("America/Argentina/Buenos_Aires")

router = APIRouter()


def get_pares_marca_categoria_usuario(db: Session, usuario: Usuario) -> Optional[list]:
    """
    Obtiene los pares (marca, categoría) asignados al usuario si no es admin/gerente.
    Retorna None si el usuario puede ver todo.
    """
    roles_completos = [RolUsuario.SUPERADMIN, RolUsuario.ADMIN, RolUsuario.GERENTE]

    if usuario.rol in roles_completos:
        return None

    pares = db.query(MarcaPM.marca, MarcaPM.categoria).filter(MarcaPM.usuario_id == usuario.id).all()
    return [(m.upper(), c.upper()) for m, c in pares] if pares else []


def aplicar_filtro_marcas_pm(query, usuario: Usuario, db: Session, pm_ids: Optional[str] = None):
    """
    Aplica filtro de pares marca+categoría del PM a una query de MLVentaMetrica.
    
    Si pm_ids está presente (usuario admin seleccionó PMs específicos), filtra por esos PMs.
    Si pm_ids NO está presente, aplica el filtro del usuario actual (comportamiento original).
    """
    # Si el usuario admin pasó pm_ids, usar esos en lugar del usuario actual
    if pm_ids:
        pm_ids_list = [int(id.strip()) for id in pm_ids.split(',') if id.strip().isdigit()]
        if pm_ids_list:
            pares_pm = db.query(MarcaPM.marca, MarcaPM.categoria).filter(
                MarcaPM.usuario_id.in_(pm_ids_list)
            ).distinct().all()
            
            if not pares_pm:
                query = query.filter(MLVentaMetrica.marca == '__NINGUNA__')
            else:
                pares_upper = [(m.upper(), c.upper()) for m, c in pares_pm]
                query = query.filter(
                    tuple_(func.upper(MLVentaMetrica.marca), func.upper(MLVentaMetrica.categoria)).in_(pares_upper)
                )
            return query
    
    # Comportamiento original: filtrar por marca+categoría del usuario actual
    pares_usuario = get_pares_marca_categoria_usuario(db, usuario)

    if pares_usuario is not None:
        if len(pares_usuario) == 0:
            query = query.filter(MLVentaMetrica.marca == '__NINGUNA__')
        else:
            query = query.filter(
                tuple_(func.upper(MLVentaMetrica.marca), func.upper(MLVentaMetrica.categoria)).in_(pares_usuario)
            )

    return query


def aplicar_filtro_tienda_oficial(query, tiendas_oficiales: Optional[str], db: Session):
    """
    Aplica filtro de tiendas oficiales por mlp_official_store_id.
    Soporta múltiples tiendas separadas por coma.
    
    Tiendas disponibles:
    - 57997: Gauss
    - 2645: TP-Link
    - 144: Forza/Verbatim
    - 191942: Multi-marca (Epson, Logitech, MGN, Razer)
    """
    if tiendas_oficiales:
        from app.models.mercadolibre_item_publicado import MercadoLibreItemPublicado
        from sqlalchemy import cast, String
        
        # Parsear múltiples tiendas
        store_ids = [int(id.strip()) for id in tiendas_oficiales.split(',') if id.strip().isdigit()]
        
        if store_ids:
            # Subquery para obtener mlp_ids de tiendas oficiales
            mlas_tienda_oficial = db.query(
                cast(MercadoLibreItemPublicado.mlp_id, String)
            ).filter(
                MercadoLibreItemPublicado.mlp_official_store_id.in_(store_ids)
            ).distinct()
            
            query = query.filter(MLVentaMetrica.mla_id.in_(mlas_tienda_oficial))
    return query


def aplicar_filtros_comunes(query, fecha_desde: Optional[str], fecha_hasta: Optional[str], 
                            marcas: Optional[str], categorias: Optional[str], 
                            tiendas_oficiales: Optional[str], db: Session):
    """
    Aplica filtros comunes a todas las queries de dashboard ML.
    Soporta múltiples valores separados por coma para marcas, categorías y tiendas.
    
    IMPORTANTE: Las fechas se interpretan en timezone Argentina (America/Argentina/Buenos_Aires).
    Esto asegura que "hoy" incluya todas las ventas del día calendario argentino,
    no del día UTC.
    """
    if fecha_desde:
        # Convertir fecha a datetime con timezone Argentina a las 00:00:00
        fecha_desde_dt = datetime.fromisoformat(fecha_desde).replace(tzinfo=ARGENTINA_TZ)
        query = query.filter(MLVentaMetrica.fecha_venta >= fecha_desde_dt)

    if fecha_hasta:
        # Convertir fecha_hasta a datetime con timezone Argentina al día siguiente a las 00:00:00
        # (para incluir todo el día hasta las 23:59:59.999999)
        fecha_hasta_dt = datetime.fromisoformat(fecha_hasta).replace(tzinfo=ARGENTINA_TZ) + timedelta(days=1)
        query = query.filter(MLVentaMetrica.fecha_venta < fecha_hasta_dt)

    if marcas:
        marcas_list = [m.strip() for m in marcas.split(',') if m.strip()]
        if marcas_list:
            query = query.filter(MLVentaMetrica.marca.in_(marcas_list))

    if categorias:
        categorias_list = [c.strip() for c in categorias.split(',') if c.strip()]
        if categorias_list:
            query = query.filter(MLVentaMetrica.categoria.in_(categorias_list))

    query = aplicar_filtro_tienda_oficial(query, tiendas_oficiales, db)
    
    return query


# Schemas de respuesta
class MetricasGeneralesResponse(BaseModel):
    """Métricas generales del dashboard"""
    total_ventas_ml: Decimal  # Monto total de ventas
    total_limpio: Decimal     # Monto después de comisiones y envío
    total_ganancia: Decimal   # Ganancia total
    total_costo: Decimal      # Costo total
    markup_porcentaje: Decimal  # Markup calculado sobre totales (ganancia/costo)
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
    markup_porcentaje: Decimal
    cantidad_operaciones: int
    cantidad_unidades: int


class VentaPorCategoriaResponse(BaseModel):
    """Ventas agrupadas por categoría"""
    categoria: str
    total_ventas: Decimal
    total_limpio: Decimal
    total_ganancia: Decimal
    markup_porcentaje: Decimal
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
    descripcion: Optional[str]
    marca: Optional[str]
    total_ventas: Decimal
    total_ganancia: Decimal
    markup_porcentaje: Decimal
    cantidad_operaciones: int
    cantidad_unidades: int


# Endpoints

@router.get("/dashboard-ml/metricas-generales", response_model=MetricasGeneralesResponse)
async def get_metricas_generales(
    fecha_desde: Optional[str] = Query(None, description="Fecha desde (YYYY-MM-DD)"),
    fecha_hasta: Optional[str] = Query(None, description="Fecha hasta (YYYY-MM-DD)"),
    marcas: Optional[str] = Query(None, description="Filtrar por marcas (separadas por coma)"),
    categorias: Optional[str] = Query(None, description="Filtrar por categorías (separadas por coma)"),
    tiendas_oficiales: Optional[str] = Query(None, description="Filtrar por tiendas oficiales (IDs separados por coma)"),
    pm_ids: Optional[str] = Query(None, description="IDs de PMs separados por coma (solo admin)"),
    db: Session = Depends(get_db),
    current_user: Usuario = Depends(get_current_user)
):
    """
    Obtiene métricas generales del dashboard.
    Si el usuario no es admin/gerente, solo ve sus marcas asignadas.
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

    # Filtrar por marcas del PM (o por pm_ids si se especificó)
    query = aplicar_filtro_marcas_pm(query, current_user, db, pm_ids)

    # Aplicar filtros comunes
    query = aplicar_filtros_comunes(query, fecha_desde, fecha_hasta, marcas, categorias, tiendas_oficiales, db)

    result = query.first()

    if not result or result.total_ventas_ml is None:
        return MetricasGeneralesResponse(
            total_ventas_ml=Decimal('0'),
            total_limpio=Decimal('0'),
            total_ganancia=Decimal('0'),
            total_costo=Decimal('0'),
            markup_porcentaje=Decimal('0'),
            cantidad_operaciones=0,
            cantidad_unidades=0,
            total_comisiones=Decimal('0'),
            total_envios=Decimal('0')
        )

    # Calcular markup sobre totales
    # markup = (ganancia_total / costo_total_sin_iva) * 100
    total_costo = Decimal(str(result.total_costo)) if result.total_costo else Decimal('0')
    total_ganancia = Decimal(str(result.total_ganancia)) if result.total_ganancia else Decimal('0')

    markup_porcentaje = Decimal('0')
    if total_costo > 0:
        markup_porcentaje = round((total_ganancia / total_costo) * Decimal('100'), 2)

    return MetricasGeneralesResponse(
        total_ventas_ml=result.total_ventas_ml or Decimal('0'),
        total_limpio=result.total_limpio or Decimal('0'),
        total_ganancia=total_ganancia,
        total_costo=total_costo,
        markup_porcentaje=markup_porcentaje,
        cantidad_operaciones=result.cantidad_operaciones or 0,
        cantidad_unidades=int(result.cantidad_unidades or 0),
        total_comisiones=result.total_comisiones or Decimal('0'),
        total_envios=result.total_envios or Decimal('0')
    )


@router.get("/dashboard-ml/por-marca", response_model=List[VentaPorMarcaResponse])
async def get_ventas_por_marca(
    fecha_desde: Optional[str] = Query(None),
    fecha_hasta: Optional[str] = Query(None),
    categorias: Optional[str] = Query(None, description="Filtrar por categorías (separadas por coma)"),
    tiendas_oficiales: Optional[str] = Query(None),
    pm_ids: Optional[str] = Query(None, description="IDs de PMs separados por coma (solo admin)"),
    limit: int = Query(20, le=100),
    db: Session = Depends(get_db),
    current_user: Usuario = Depends(get_current_user)
):
    """
    Obtiene ventas agrupadas por marca.
    Si el usuario no es admin/gerente, solo ve sus marcas asignadas.
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

    # Filtrar por marcas del PM (o por pm_ids si se especificó)
    query = aplicar_filtro_marcas_pm(query, current_user, db, pm_ids)

    query = aplicar_filtros_comunes(query, fecha_desde, fecha_hasta, None, categorias, tiendas_oficiales, db)

    resultados = query.group_by(MLVentaMetrica.marca).order_by(desc('total_ventas')).limit(limit).all()

    return [
        VentaPorMarcaResponse(
            marca=r.marca,
            total_ventas=r.total_ventas or Decimal('0'),
            total_limpio=r.total_limpio or Decimal('0'),
            total_ganancia=r.total_ganancia or Decimal('0'),
            markup_porcentaje=((r.total_ganancia / r.total_costo) * Decimal('100')) if r.total_costo and r.total_costo > 0 else Decimal('0'),
            cantidad_operaciones=r.cantidad_operaciones or 0,
            cantidad_unidades=int(r.cantidad_unidades or 0)
        )
        for r in resultados
    ]


@router.get("/dashboard-ml/por-categoria", response_model=List[VentaPorCategoriaResponse])
async def get_ventas_por_categoria(
    fecha_desde: Optional[str] = Query(None),
    fecha_hasta: Optional[str] = Query(None),
    marcas: Optional[str] = Query(None, description="Filtrar por marcas (separadas por coma)"),
    tiendas_oficiales: Optional[str] = Query(None),
    pm_ids: Optional[str] = Query(None, description="IDs de PMs separados por coma (solo admin)"),
    limit: int = Query(20, le=100),
    db: Session = Depends(get_db),
    current_user: Usuario = Depends(get_current_user)
):
    """
    Obtiene ventas agrupadas por categoría.
    Si el usuario no es admin/gerente, solo ve sus marcas asignadas.
    """
    query = db.query(
        MLVentaMetrica.categoria,
        func.sum(MLVentaMetrica.monto_total).label('total_ventas'),
        func.sum(MLVentaMetrica.monto_limpio).label('total_limpio'),
        func.sum(MLVentaMetrica.ganancia).label('total_ganancia'),
        func.sum(MLVentaMetrica.costo_total_sin_iva).label('total_costo'),
        func.count(MLVentaMetrica.id).label('cantidad_operaciones')
    ).filter(MLVentaMetrica.categoria.isnot(None))

    # Filtrar por marcas del PM (o por pm_ids si se especificó)
    query = aplicar_filtro_marcas_pm(query, current_user, db, pm_ids)

    query = aplicar_filtros_comunes(query, fecha_desde, fecha_hasta, marcas, None, tiendas_oficiales, db)

    resultados = query.group_by(MLVentaMetrica.categoria).order_by(desc('total_ventas')).limit(limit).all()

    return [
        VentaPorCategoriaResponse(
            categoria=r.categoria,
            total_ventas=r.total_ventas or Decimal('0'),
            total_limpio=r.total_limpio or Decimal('0'),
            total_ganancia=r.total_ganancia or Decimal('0'),
            markup_porcentaje=((r.total_ganancia / r.total_costo) * Decimal('100')) if r.total_costo and r.total_costo > 0 else Decimal('0'),
            cantidad_operaciones=r.cantidad_operaciones or 0
        )
        for r in resultados
    ]


@router.get("/dashboard-ml/por-logistica", response_model=List[VentaPorLogisticaResponse])
async def get_ventas_por_logistica(
    fecha_desde: Optional[str] = Query(None),
    fecha_hasta: Optional[str] = Query(None),
    marcas: Optional[str] = Query(None, description="Filtrar por marcas (separadas por coma)"),
    categorias: Optional[str] = Query(None, description="Filtrar por categorías (separadas por coma)"),
    tiendas_oficiales: Optional[str] = Query(None),
    pm_ids: Optional[str] = Query(None, description="IDs de PMs separados por coma (solo admin)"),
    db: Session = Depends(get_db),
    current_user: Usuario = Depends(get_current_user)
):
    """
    Obtiene ventas agrupadas por tipo de logística.
    Si el usuario no es admin/gerente, solo ve sus marcas asignadas.
    """
    query = db.query(
        MLVentaMetrica.tipo_logistica,
        func.sum(MLVentaMetrica.monto_total).label('total_ventas'),
        func.sum(MLVentaMetrica.costo_envio_ml).label('total_envios'),
        func.count(MLVentaMetrica.id).label('cantidad_operaciones')
    ).filter(MLVentaMetrica.tipo_logistica.isnot(None))

    # Filtrar por marcas del PM (o por pm_ids si se especificó)
    query = aplicar_filtro_marcas_pm(query, current_user, db, pm_ids)

    query = aplicar_filtros_comunes(query, fecha_desde, fecha_hasta, marcas, categorias, tiendas_oficiales, db)

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
    marcas: Optional[str] = Query(None, description="Filtrar por marcas (separadas por coma)"),
    categorias: Optional[str] = Query(None, description="Filtrar por categorías (separadas por coma)"),
    tiendas_oficiales: Optional[str] = Query(None),
    pm_ids: Optional[str] = Query(None, description="IDs de PMs separados por coma (solo admin)"),
    db: Session = Depends(get_db),
    current_user: Usuario = Depends(get_current_user)
):
    """
    Obtiene ventas agrupadas por día.
    Si el usuario no es admin/gerente, solo ve sus marcas asignadas.
    """
    fecha_truncada = func.date(MLVentaMetrica.fecha_venta)

    query = db.query(
        fecha_truncada.label('fecha'),
        func.sum(MLVentaMetrica.monto_total).label('total_ventas'),
        func.sum(MLVentaMetrica.monto_limpio).label('total_limpio'),
        func.sum(MLVentaMetrica.ganancia).label('total_ganancia'),
        func.count(MLVentaMetrica.id).label('cantidad_operaciones')
    )

    # Filtrar por marcas del PM (o por pm_ids si se especificó)
    query = aplicar_filtro_marcas_pm(query, current_user, db, pm_ids)

    query = aplicar_filtros_comunes(query, fecha_desde, fecha_hasta, marcas, categorias, tiendas_oficiales, db)

    resultados = query.group_by(fecha_truncada).order_by(fecha_truncada).all()

    return [
        VentaDiariaResponse(
            fecha=r.fecha,
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
    marcas: Optional[str] = Query(None, description="Filtrar por marcas (separadas por coma)"),
    categorias: Optional[str] = Query(None, description="Filtrar por categorías (separadas por coma)"),
    tiendas_oficiales: Optional[str] = Query(None),
    pm_ids: Optional[str] = Query(None, description="IDs de PMs separados por coma (solo admin)"),
    limit: int = Query(10, le=100),
    db: Session = Depends(get_db),
    current_user: Usuario = Depends(get_current_user)
):
    """
    Obtiene los productos más vendidos.
    Si el usuario no es admin/gerente, solo ve sus marcas asignadas.
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

    # Filtrar por marcas del PM (o por pm_ids si se especificó)
    query = aplicar_filtro_marcas_pm(query, current_user, db, pm_ids)

    query = aplicar_filtros_comunes(query, fecha_desde, fecha_hasta, marcas, categorias, tiendas_oficiales, db)

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
            markup_porcentaje=((r.total_ganancia / r.total_costo) * Decimal('100')) if r.total_costo and r.total_costo > 0 else Decimal('0'),
            cantidad_operaciones=r.cantidad_operaciones or 0,
            cantidad_unidades=int(r.cantidad_unidades or 0)
        )
        for r in resultados
    ]


@router.get("/dashboard-ml/marcas-disponibles")
async def get_marcas_disponibles(
    fecha_desde: Optional[str] = Query(None),
    fecha_hasta: Optional[str] = Query(None),
    tiendas_oficiales: Optional[str] = Query(None),
    pm_ids: Optional[str] = Query(None),
    categorias: Optional[str] = Query(None),
    db: Session = Depends(get_db),
    current_user: Usuario = Depends(get_current_user)
):
    """
    Obtiene lista de marcas disponibles en las métricas con filtros aplicados.
    Aplica filtros de fecha, tiendas oficiales, PMs y categorías.
    NO aplica filtro de marcas (para evitar circularidad).
    """
    query = db.query(MLVentaMetrica.marca).filter(MLVentaMetrica.marca.isnot(None))

    # Aplicar filtros comunes (fecha, tiendas, categorías) - SIN marcas
    query = aplicar_filtros_comunes(query, fecha_desde, fecha_hasta, 
                                     None, categorias,  # marcas=None para evitar circularidad
                                     tiendas_oficiales, db)
    
    # Aplicar filtro de PM por separado
    query = aplicar_filtro_marcas_pm(query, current_user, db, pm_ids)

    marcas = query.distinct().order_by(MLVentaMetrica.marca).all()
    return [m[0] for m in marcas]


@router.get("/dashboard-ml/categorias-disponibles")
async def get_categorias_disponibles(
    fecha_desde: Optional[str] = Query(None),
    fecha_hasta: Optional[str] = Query(None),
    tiendas_oficiales: Optional[str] = Query(None),
    pm_ids: Optional[str] = Query(None),
    marcas: Optional[str] = Query(None),
    db: Session = Depends(get_db),
    current_user: Usuario = Depends(get_current_user)
):
    """
    Obtiene lista de categorías disponibles en las métricas con filtros aplicados.
    Aplica filtros de fecha, tiendas oficiales, PMs y marcas.
    NO aplica filtro de categorías (para evitar circularidad).
    """
    query = db.query(MLVentaMetrica.categoria).filter(MLVentaMetrica.categoria.isnot(None))

    # Aplicar filtros comunes (fecha, tiendas, marcas) - SIN categorías
    query = aplicar_filtros_comunes(query, fecha_desde, fecha_hasta, 
                                     marcas, None,  # categorias=None para evitar circularidad
                                     tiendas_oficiales, db)
    
    # Aplicar filtro de PM por separado
    query = aplicar_filtro_marcas_pm(query, current_user, db, pm_ids)

    categorias = query.distinct().order_by(MLVentaMetrica.categoria).all()
    return [c[0] for c in categorias]


@router.get("/dashboard-ml/mis-marcas")
async def get_mis_marcas(
    db: Session = Depends(get_db),
    current_user: Usuario = Depends(get_current_user)
):
    """
    Obtiene los pares marca+categoría asignados al usuario actual.
    Si es admin/gerente, retorna None indicando que puede ver todo.
    """
    pares = get_pares_marca_categoria_usuario(db, current_user)
    if pares is None:
        return {
            "puede_ver_todo": True,
            "marcas": [],
            "pares": []
        }
    # Extraer marcas únicas para retrocompatibilidad
    marcas_unicas = list({m for m, c in pares})
    return {
        "puede_ver_todo": False,
        "marcas": marcas_unicas,
        "pares": [{"marca": m, "categoria": c} for m, c in pares]
    }
