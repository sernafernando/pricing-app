from typing import List, Optional

from fastapi import APIRouter, Depends, Query
from sqlalchemy.orm import Session
from sqlalchemy import or_, text

from app.core.database import get_db
from app.models.cur_exch_history import CurExchHistory
from app.models.producto import ProductoERP
from app.models.usuario import Usuario
from app.api.deps import get_current_user
from app.api.endpoints.rentabilidad_schemas import ProductoBusqueda
from app.services.pm_scope import aplicar_filtro_marcas_pm

router = APIRouter()


@router.get("/tipo-cambio-hoy")
def obtener_tipo_cambio(db: Session = Depends(get_db), current_user: Usuario = Depends(get_current_user)):
    """Obtiene el tipo de cambio USD/ARS más reciente (primero tipo_cambio, fallback CurExchHistory)"""
    from app.models.tipo_cambio import TipoCambio

    # Primero intentar con tipo_cambio
    tc = db.query(TipoCambio).filter(TipoCambio.moneda == "USD").order_by(TipoCambio.fecha.desc()).first()
    if tc and tc.venta:
        return {"tipo_cambio": float(tc.venta), "fecha": tc.fecha.isoformat() if tc.fecha else None}

    # Fallback a CurExchHistory
    tipo_cambio = db.query(CurExchHistory).order_by(CurExchHistory.ceh_cd.desc()).first()

    if tipo_cambio:
        return {
            "tipo_cambio": float(tipo_cambio.ceh_exchange),
            "fecha": tipo_cambio.ceh_cd.isoformat() if tipo_cambio.ceh_cd else None,
        }

    return {"tipo_cambio": 1000.0, "fecha": None}  # Default fallback


@router.get("/buscar-productos-erp")
def buscar_productos_erp(
    q: str = Query(..., min_length=2, description="Buscar por código o descripción"),
    db: Session = Depends(get_db),
    current_user: Usuario = Depends(get_current_user),
):
    """Busca productos en productos_erp por código o descripción, con costo actual"""
    query = """
    SELECT
        p.item_id,
        p.codigo,
        p.descripcion,
        p.marca,
        p.costo,
        p.moneda_costo
    FROM productos_erp p
    WHERE (p.codigo ILIKE :buscar OR p.descripcion ILIKE :buscar)
    ORDER BY p.codigo
    LIMIT 50
    """

    result = db.execute(text(query), {"buscar": f"%{q}%"}).fetchall()

    return [
        {
            "item_id": r.item_id,
            "codigo": r.codigo or str(r.item_id),
            "descripcion": r.descripcion or "",
            "marca": r.marca,
            "costo_unitario": float(r.costo) if r.costo else None,
            "moneda_costo": r.moneda_costo,
        }
        for r in result
    ]


@router.get("/buscar-productos-catalogo", response_model=List[ProductoBusqueda])
def buscar_productos_catalogo(
    q: str = Query(..., min_length=2, description="Buscar por código (EAN) o descripción"),
    pm_ids: Optional[str] = Query(None, description="IDs de PMs separados por coma (solo full-view)"),
    db: Session = Depends(get_db),
    current_user: Usuario = Depends(get_current_user),
):
    """Busca productos en el catálogo (`productos_erp`) por código o descripción,
    SIN importar si tuvieron ventas o stock.

    Usado por el modal de offsets (los 3 canales), donde hay que poder aplicar un
    offset a cualquier producto vigente, no solo a los vendidos en el período.
    Respeta el scope de PM del usuario (un PM solo ve sus marcas asignadas).
    """
    query = db.query(
        ProductoERP.item_id,
        ProductoERP.codigo,
        ProductoERP.descripcion,
        ProductoERP.marca,
        ProductoERP.categoria,
    ).filter(
        ProductoERP.activo.is_(True),
        or_(ProductoERP.codigo.ilike(f"%{q}%"), ProductoERP.descripcion.ilike(f"%{q}%")),
    )

    query = aplicar_filtro_marcas_pm(
        query, current_user, db, pm_ids, marca_col=ProductoERP.marca, categoria_col=ProductoERP.categoria
    )

    resultados = query.distinct().order_by(ProductoERP.codigo).limit(50).all()

    return [
        ProductoBusqueda(
            item_id=r.item_id,
            codigo=r.codigo or str(r.item_id),
            descripcion=r.descripcion or "",
            marca=r.marca,
            categoria=r.categoria,
        )
        for r in resultados
        if r.item_id
    ]
