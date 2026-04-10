from fastapi import APIRouter, Depends, Query
from sqlalchemy.orm import Session
from typing import Optional
from datetime import date, datetime, timedelta

from app.core.database import get_db
from app.models.ml_venta_metrica import MLVentaMetrica
from app.models.usuario import Usuario
from app.api.deps import get_current_user
from app.api.endpoints.rentabilidad_shared import aplicar_filtro_marcas_pm, aplicar_filtro_tienda_oficial

router = APIRouter()


@router.get("/rentabilidad/filtros")
def obtener_filtros_disponibles(
    fecha_desde: date = Query(...),
    fecha_hasta: date = Query(...),
    marcas: Optional[str] = Query(None),
    categorias: Optional[str] = Query(None),
    subcategorias: Optional[str] = Query(None),
    tiendas_oficiales: Optional[str] = Query(None, description="IDs de tiendas oficiales separados por coma"),
    pm_ids: Optional[str] = Query(None, description="IDs de PMs separados por coma (solo admin)"),
    db: Session = Depends(get_db),
    current_user: Usuario = Depends(get_current_user),
):
    """
    Obtiene los valores disponibles para los filtros basado en los datos del período.
    Los filtros se retroalimentan entre sí (bidireccional).
    Soporta filtros de PMs y múltiples tiendas oficiales.
    """
    # Usar | como separador para evitar conflictos con comas en nombres
    lista_marcas = [m.strip() for m in marcas.split("|")] if marcas else []
    lista_categorias = [c.strip() for c in categorias.split("|")] if categorias else []
    lista_subcategorias = [s.strip() for s in subcategorias.split("|")] if subcategorias else []

    # Convertir fechas a datetime para comparación correcta
    fecha_desde_dt = datetime.combine(fecha_desde, datetime.min.time())
    fecha_hasta_dt = datetime.combine(fecha_hasta + timedelta(days=1), datetime.min.time())

    # Marcas disponibles (filtradas por categorías y subcategorías seleccionadas)
    marcas_query = db.query(MLVentaMetrica.marca).filter(
        MLVentaMetrica.fecha_venta >= fecha_desde_dt,
        MLVentaMetrica.fecha_venta < fecha_hasta_dt,
        MLVentaMetrica.marca.isnot(None),
    )
    if lista_categorias:
        marcas_query = marcas_query.filter(MLVentaMetrica.categoria.in_(lista_categorias))
    if lista_subcategorias:
        marcas_query = marcas_query.filter(MLVentaMetrica.subcategoria.in_(lista_subcategorias))
    marcas_query = aplicar_filtro_tienda_oficial(marcas_query, tiendas_oficiales, db)
    marcas_query = aplicar_filtro_marcas_pm(marcas_query, current_user, db, pm_ids)
    marcas_disponibles = marcas_query.distinct().order_by(MLVentaMetrica.marca).all()

    # Categorías disponibles (filtradas por marcas y subcategorías seleccionadas)
    cat_query = db.query(MLVentaMetrica.categoria).filter(
        MLVentaMetrica.fecha_venta >= fecha_desde_dt,
        MLVentaMetrica.fecha_venta < fecha_hasta_dt,
        MLVentaMetrica.categoria.isnot(None),
    )
    if lista_marcas:
        cat_query = cat_query.filter(MLVentaMetrica.marca.in_(lista_marcas))
    if lista_subcategorias:
        cat_query = cat_query.filter(MLVentaMetrica.subcategoria.in_(lista_subcategorias))
    cat_query = aplicar_filtro_tienda_oficial(cat_query, tiendas_oficiales, db)
    cat_query = aplicar_filtro_marcas_pm(cat_query, current_user, db, pm_ids)
    categorias_disponibles = cat_query.distinct().order_by(MLVentaMetrica.categoria).all()

    # Subcategorías disponibles (filtradas por marcas y categorías seleccionadas)
    subcat_query = db.query(MLVentaMetrica.subcategoria).filter(
        MLVentaMetrica.fecha_venta >= fecha_desde_dt,
        MLVentaMetrica.fecha_venta < fecha_hasta_dt,
        MLVentaMetrica.subcategoria.isnot(None),
    )
    if lista_marcas:
        subcat_query = subcat_query.filter(MLVentaMetrica.marca.in_(lista_marcas))
    if lista_categorias:
        subcat_query = subcat_query.filter(MLVentaMetrica.categoria.in_(lista_categorias))
    subcat_query = aplicar_filtro_tienda_oficial(subcat_query, tiendas_oficiales, db)
    subcat_query = aplicar_filtro_marcas_pm(subcat_query, current_user, db, pm_ids)
    subcategorias_disponibles = subcat_query.distinct().order_by(MLVentaMetrica.subcategoria).all()

    return {
        "marcas": [m[0] for m in marcas_disponibles if m[0]],
        "categorias": [c[0] for c in categorias_disponibles if c[0]],
        "subcategorias": [s[0] for s in subcategorias_disponibles if s[0]],
    }
