from fastapi import APIRouter, Depends, HTTPException
from sqlalchemy.orm import Session
from app.core.database import get_db
from app.services.erp_sync import sincronizar_erp

router = APIRouter()

@router.post("/sync")
async def sync_erp(db: Session = Depends(get_db)):
    """Sincroniza productos desde el ERP"""
    try:
        stats = await sincronizar_erp(db)
        return {
            "status": "success",
            "stats": stats
        }
    except Exception as e:
        raise HTTPException(status_code=500, detail=str(e))

from app.services.ml_sync import sincronizar_publicaciones_ml, obtener_publicaciones_por_item

@router.post("/sync-ml")
async def sincronizar_ml(db: Session = Depends(get_db)):
    """Sincroniza publicaciones de Mercado Libre"""
    resultado = await sincronizar_publicaciones_ml(db)
    return resultado

@router.get("/publicaciones-ml/{item_id}")
async def obtener_publicaciones(item_id: int, db: Session = Depends(get_db)):
    """Obtiene publicaciones ML de un producto"""
    pubs = obtener_publicaciones_por_item(db, item_id)
    
    return {
        "item_id": item_id,
        "total": len(pubs),
        "publicaciones": [
            {
                "mla": p.mla,
                "item_title": p.item_title,
                "pricelist_id": p.pricelist_id,
                "lista_nombre": p.lista_nombre,
            }
            for p in pubs
        ]
    }
