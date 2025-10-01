from fastapi import APIRouter, Depends, HTTPException
from sqlalchemy.orm import Session
from pydantic import BaseModel

from app.core.database import get_db
from app.models.comision_config import GrupoComision, SubcategoriaGrupo, ComisionListaGrupo

router = APIRouter()

@router.get("/admin/comisiones/{grupo_id}")
async def obtener_comisiones_grupo(grupo_id: int, db: Session = Depends(get_db)):
    """Obtiene todas las comisiones de un grupo"""
    comisiones = db.query(ComisionListaGrupo).filter(
        ComisionListaGrupo.grupo_id == grupo_id
    ).all()
    
    return {
        "grupo_id": grupo_id,
        "comisiones": [
            {
                "pricelist_id": c.pricelist_id,
                "comision": c.comision_porcentaje
            }
            for c in comisiones
        ]
    }

@router.get("/admin/comision/{pricelist_id}/{grupo_id}")
async def obtener_comision_especifica(
    pricelist_id: int,
    grupo_id: int,
    db: Session = Depends(get_db)
):
    """Obtiene la comisión para una lista y grupo específicos"""
    comision = db.query(ComisionListaGrupo).filter(
        ComisionListaGrupo.pricelist_id == pricelist_id,
        ComisionListaGrupo.grupo_id == grupo_id
    ).first()
    
    if not comision:
        raise HTTPException(404, "Comisión no encontrada")
    
    return {
        "pricelist_id": pricelist_id,
        "grupo_id": grupo_id,
        "comision": comision.comision_porcentaje
    }

@router.get("/admin/subcategorias-grupos")
async def listar_subcategorias_grupos(db: Session = Depends(get_db)):
    """Lista todas las subcategorías y sus grupos asignados"""
    mappings = db.query(SubcategoriaGrupo).all()
    return {
        "mappings": [
            {
                "subcat_id": m.subcat_id,
                "grupo_id": m.grupo_id
            }
            for m in mappings
        ]
    }

from app.services.bna_scraper import actualizar_tipo_cambio

@router.post("/admin/actualizar-tipo-cambio")
async def actualizar_tc_manual(db: Session = Depends(get_db)):
    """Actualiza el tipo de cambio scrapeando el BNA"""
    resultado = await actualizar_tipo_cambio(db)
    return resultado

@router.get("/admin/tipo-cambio-actual")
async def obtener_tc_actual(db: Session = Depends(get_db)):
    """Obtiene el tipo de cambio actual"""
    from app.services.pricing_calculator import obtener_tipo_cambio_actual
    tc = obtener_tipo_cambio_actual(db, "USD")
    
    if not tc:
        raise HTTPException(404, "No hay tipo de cambio disponible")
    
    return {
        "moneda": "USD",
        "venta": tc,
        "fecha": date.today().isoformat()
    }
