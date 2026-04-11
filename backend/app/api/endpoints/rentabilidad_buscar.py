from fastapi import APIRouter, Depends, Query
from sqlalchemy.orm import Session
from sqlalchemy import or_
from typing import List, Optional
from datetime import date, datetime, timedelta

from app.core.database import get_db
from app.models.ml_venta_metrica import MLVentaMetrica
from app.models.usuario import Usuario
from app.api.deps import get_current_user
from app.api.endpoints.rentabilidad_shared import aplicar_filtro_marcas_pm, aplicar_filtro_tienda_oficial
from app.api.endpoints.rentabilidad_schemas import ProductoBusqueda

router = APIRouter()


@router.get("/rentabilidad/buscar-productos", response_model=List[ProductoBusqueda])
def buscar_productos(
    q: str = Query(..., min_length=2, description="Término de búsqueda"),
    fecha_desde: date = Query(...),
    fecha_hasta: date = Query(...),
    tiendas_oficiales: Optional[str] = Query(None, description="IDs de tiendas oficiales separados por coma"),
    pm_ids: Optional[str] = Query(None, description="IDs de PMs separados por coma (solo admin)"),
    db: Session = Depends(get_db),
    current_user: Usuario = Depends(get_current_user),
):
    """
    Busca productos por código o descripción que tengan ventas en el período.
    Soporta filtros de PMs y múltiples tiendas oficiales.
    """
    # Convertir fechas a datetime para comparación correcta
    fecha_desde_dt = datetime.combine(fecha_desde, datetime.min.time())
    fecha_hasta_dt = datetime.combine(fecha_hasta + timedelta(days=1), datetime.min.time())

    # Buscar productos con ventas en el período
    query = db.query(
        MLVentaMetrica.item_id,
        MLVentaMetrica.codigo,
        MLVentaMetrica.descripcion,
        MLVentaMetrica.marca,
        MLVentaMetrica.categoria,
    ).filter(
        MLVentaMetrica.fecha_venta >= fecha_desde_dt,
        MLVentaMetrica.fecha_venta < fecha_hasta_dt,
        or_(MLVentaMetrica.codigo.ilike(f"%{q}%"), MLVentaMetrica.descripcion.ilike(f"%{q}%")),
    )

    query = aplicar_filtro_tienda_oficial(query, tiendas_oficiales, db)
    query = aplicar_filtro_marcas_pm(query, current_user, db, pm_ids)
    query = query.distinct().limit(50)

    resultados = query.all()

    return [
        ProductoBusqueda(
            item_id=r.item_id,
            codigo=r.codigo or "",
            descripcion=r.descripcion or "",
            marca=r.marca,
            categoria=r.categoria,
        )
        for r in resultados
        if r.item_id
    ]
