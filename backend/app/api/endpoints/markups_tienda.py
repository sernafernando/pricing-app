"""
Endpoints para gestión de markups de tienda
"""
from fastapi import APIRouter, Depends, HTTPException, status
from sqlalchemy.orm import Session
from sqlalchemy import func
from typing import List, Optional
from pydantic import BaseModel

from app.core.database import get_db
from app.api.deps import get_current_user
from app.models.usuario import Usuario
from app.models.markup_tienda import MarkupTiendaBrand
from app.services.permisos_service import verificar_permiso

router = APIRouter(prefix="/markups-tienda", tags=["markups-tienda"])


# =============================================================================
# SCHEMAS
# =============================================================================

class MarkupBrandCreate(BaseModel):
    comp_id: int
    brand_id: int
    brand_desc: Optional[str] = None
    markup_porcentaje: float
    activo: bool = True
    notas: Optional[str] = None


class MarkupBrandUpdate(BaseModel):
    markup_porcentaje: Optional[float] = None
    activo: Optional[bool] = None
    notas: Optional[str] = None


class MarkupBrandResponse(BaseModel):
    id: int
    comp_id: int
    brand_id: int
    brand_desc: Optional[str]
    markup_porcentaje: float
    activo: bool
    notas: Optional[str]
    created_at: Optional[str]
    updated_at: Optional[str]

    class Config:
        from_attributes = True


class BrandWithMarkup(BaseModel):
    """Marca con información de markup si existe"""
    comp_id: int
    brand_id: int
    brand_desc: str
    markup_id: Optional[int] = None
    markup_porcentaje: Optional[float] = None
    markup_activo: Optional[bool] = None
    markup_notas: Optional[str] = None


# =============================================================================
# ENDPOINTS
# =============================================================================

@router.get("/brands", response_model=List[BrandWithMarkup])
async def listar_brands_con_markups(
    busqueda: Optional[str] = None,
    solo_con_markup: bool = False,
    db: Session = Depends(get_db),
    current_user: Usuario = Depends(get_current_user)
):
    """
    Lista todas las marcas con sus markups asignados (si tienen).
    Permite búsqueda por nombre de marca.
    """
    if not verificar_permiso(db, current_user, 'productos.gestionar_markups_tienda'):
        raise HTTPException(
            status_code=status.HTTP_403_FORBIDDEN,
            detail="No tienes permiso para gestionar markups de tienda"
        )

    # Query base para obtener marcas de tb_brand
    query = db.execute("""
        SELECT DISTINCT
            b.comp_id,
            b.brand_id,
            b.brand_desc,
            m.id as markup_id,
            m.markup_porcentaje,
            m.activo as markup_activo,
            m.notas as markup_notas
        FROM tb_brand b
        LEFT JOIN markups_tienda_brand m ON b.comp_id = m.comp_id AND b.brand_id = m.brand_id
        WHERE 1=1
        {where_clause}
        ORDER BY b.brand_desc
    """.format(
        where_clause=f"AND LOWER(b.brand_desc) LIKE LOWER('%{busqueda}%')" if busqueda else ""
    ))

    results = []
    for row in query:
        # Si solo_con_markup es True, filtrar solo los que tienen markup
        if solo_con_markup and row.markup_id is None:
            continue

        results.append(BrandWithMarkup(
            comp_id=row.comp_id,
            brand_id=row.brand_id,
            brand_desc=row.brand_desc,
            markup_id=row.markup_id,
            markup_porcentaje=row.markup_porcentaje,
            markup_activo=row.markup_activo,
            markup_notas=row.markup_notas
        ))

    return results


@router.post("/brands/{comp_id}/{brand_id}/markup", response_model=MarkupBrandResponse)
async def crear_o_actualizar_markup_brand(
    comp_id: int,
    brand_id: int,
    data: MarkupBrandCreate,
    db: Session = Depends(get_db),
    current_user: Usuario = Depends(get_current_user)
):
    """
    Crea o actualiza el markup para una marca específica.
    """
    if not verificar_permiso(db, current_user, 'productos.gestionar_markups_tienda'):
        raise HTTPException(
            status_code=status.HTTP_403_FORBIDDEN,
            detail="No tienes permiso para gestionar markups de tienda"
        )

    # Verificar si ya existe un markup para esta marca
    existing = db.query(MarkupTiendaBrand).filter(
        MarkupTiendaBrand.comp_id == comp_id,
        MarkupTiendaBrand.brand_id == brand_id
    ).first()

    if existing:
        # Actualizar existente
        existing.markup_porcentaje = data.markup_porcentaje
        existing.activo = data.activo
        existing.notas = data.notas
        existing.brand_desc = data.brand_desc
        existing.updated_by_id = current_user.id
        db.commit()
        db.refresh(existing)
        return existing
    else:
        # Crear nuevo
        nuevo_markup = MarkupTiendaBrand(
            comp_id=data.comp_id,
            brand_id=data.brand_id,
            brand_desc=data.brand_desc,
            markup_porcentaje=data.markup_porcentaje,
            activo=data.activo,
            notas=data.notas,
            created_by_id=current_user.id
        )
        db.add(nuevo_markup)
        db.commit()
        db.refresh(nuevo_markup)
        return nuevo_markup


@router.delete("/brands/{comp_id}/{brand_id}/markup")
async def eliminar_markup_brand(
    comp_id: int,
    brand_id: int,
    db: Session = Depends(get_db),
    current_user: Usuario = Depends(get_current_user)
):
    """
    Elimina el markup de una marca específica.
    """
    if not verificar_permiso(db, current_user, 'productos.gestionar_markups_tienda'):
        raise HTTPException(
            status_code=status.HTTP_403_FORBIDDEN,
            detail="No tienes permiso para gestionar markups de tienda"
        )

    markup = db.query(MarkupTiendaBrand).filter(
        MarkupTiendaBrand.comp_id == comp_id,
        MarkupTiendaBrand.brand_id == brand_id
    ).first()

    if not markup:
        raise HTTPException(
            status_code=status.HTTP_404_NOT_FOUND,
            detail="Markup no encontrado"
        )

    db.delete(markup)
    db.commit()

    return {"success": True, "message": "Markup eliminado correctamente"}


@router.get("/stats")
async def obtener_estadisticas_markups(
    db: Session = Depends(get_db),
    current_user: Usuario = Depends(get_current_user)
):
    """
    Obtiene estadísticas de los markups configurados.
    """
    if not verificar_permiso(db, current_user, 'productos.gestionar_markups_tienda'):
        raise HTTPException(
            status_code=status.HTTP_403_FORBIDDEN,
            detail="No tienes permiso para gestionar markups de tienda"
        )

    total_marcas = db.execute("SELECT COUNT(DISTINCT brand_id) FROM tb_brand").scalar()
    total_con_markup = db.query(func.count(MarkupTiendaBrand.id)).filter(
        MarkupTiendaBrand.activo == True
    ).scalar()
    total_inactivos = db.query(func.count(MarkupTiendaBrand.id)).filter(
        MarkupTiendaBrand.activo == False
    ).scalar()

    markup_promedio = db.query(func.avg(MarkupTiendaBrand.markup_porcentaje)).filter(
        MarkupTiendaBrand.activo == True
    ).scalar()

    return {
        "total_marcas": total_marcas,
        "total_con_markup": total_con_markup,
        "total_sin_markup": total_marcas - total_con_markup - total_inactivos,
        "total_inactivos": total_inactivos,
        "markup_promedio": round(float(markup_promedio or 0), 2)
    }
