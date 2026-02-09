from fastapi import APIRouter, Depends, BackgroundTasks
from sqlalchemy.orm import Session
from app.core.database import get_db
from app.services.sync_precios_ml import sincronizar_precios_ml, PRICELISTS
from app.api.deps import get_current_user

router = APIRouter()

@router.post("/sync-ml/precios")
async def sincronizar_precios(
    background_tasks: BackgroundTasks,
    pricelist_id: int = None,
    db: Session = Depends(get_db),
    current_user = Depends(get_current_user)
):
    """
    Sincroniza precios de MercadoLibre
    Si pricelist_id es None, sincroniza todas las listas
    """
    
    # Ejecutar en background para no bloquear
    background_tasks.add_task(sincronizar_precios_ml, db, pricelist_id)
    
    return {
        "message": "Sincronización iniciada",
        "listas": list(PRICELISTS.keys()) if not pricelist_id else [pricelist_id]
    }

@router.get("/sync-ml/listas")
async def listar_listas(current_user = Depends(get_current_user)):
    """Lista las pricelists disponibles"""
    return {"listas": PRICELISTS}
