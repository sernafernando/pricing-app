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

from app.services.google_sheets_sync import sincronizar_ofertas_sheets

@router.post("/sync-sheets")
async def sincronizar_sheets(db: Session = Depends(get_db)):
    """Sincroniza ofertas desde Google Sheets"""
    resultado = sincronizar_ofertas_sheets(db)
    return resultado

@router.get("/debug-ofertas-ignoradas")
async def debug_ofertas(db: Session = Depends(get_db)):
    """Muestra MLA de ofertas que no están en publicaciones"""
    from app.services.google_sheets_sync import obtener_datos_sheets
    
    data = obtener_datos_sheets()
    mlas_sheets = set(row.get('MLA', '').strip() for row in data if row.get('MLA'))
    
    from app.models.publicacion_ml import PublicacionML
    mlas_db = set(p.mla for p in db.query(PublicacionML.mla).all())
    
    no_encontrados = list(mlas_sheets - mlas_db)
    
    return {
        "total_mlas_sheets": len(mlas_sheets),
        "total_mlas_db": len(mlas_db),
        "no_encontrados": len(no_encontrados),
        "sample_no_encontrados": no_encontrados[:20]
    }
