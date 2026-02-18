import asyncio
import io
import sys
from datetime import datetime

from fastapi import APIRouter, Depends, BackgroundTasks
from fastapi.responses import StreamingResponse
from sqlalchemy.orm import Session
from app.core.database import get_db, SessionLocal
from app.services.sync_precios_ml import sincronizar_precios_ml, PRICELISTS
from app.api.deps import get_current_user

router = APIRouter()


@router.post("/sync-ml/precios")
async def sincronizar_precios(
    background_tasks: BackgroundTasks,
    pricelist_id: int = None,
    db: Session = Depends(get_db),
    current_user=Depends(get_current_user),
):
    """
    Sincroniza precios de MercadoLibre
    Si pricelist_id es None, sincroniza todas las listas
    """

    # Ejecutar en background para no bloquear
    background_tasks.add_task(sincronizar_precios_ml, db, pricelist_id)

    return {
        "message": "Sincronización iniciada",
        "listas": list(PRICELISTS.keys()) if not pricelist_id else [pricelist_id],
    }


@router.get("/sync-ml/listas")
async def listar_listas(current_user=Depends(get_current_user)):
    """Lista las pricelists disponibles"""
    return {"listas": PRICELISTS}


@router.post("/sync-ml/publicaciones-full")
async def sincronizar_publicaciones_full(
    current_user=Depends(get_current_user),
):
    """
    Ejecuta sync_ml_items_publicados_full (GBP) + sync_ml_publications_incremental (API ML).
    Retorna el log completo como streaming text para mostrar progreso en el frontend.
    """
    from app.scripts.sync_ml_items_publicados_full import sync_items_publicados_full
    from app.scripts.sync_ml_publications_incremental import sync_ml_publications_incremental

    async def generate_log():
        log_buffer = io.StringIO()
        old_stdout = sys.stdout

        # Paso 1: Sync items publicados desde GBP
        yield f"[{datetime.now().strftime('%H:%M:%S')}] === PASO 1/2: Sincronizar Items Publicados (GBP) ===\n"
        db = SessionLocal()
        try:
            sys.stdout = log_buffer
            await sync_items_publicados_full(db)
            sys.stdout = old_stdout
            output = log_buffer.getvalue()
            log_buffer.truncate(0)
            log_buffer.seek(0)
            yield output
        except Exception as e:
            sys.stdout = old_stdout
            yield f"ERROR en items publicados: {str(e)}\n"
        finally:
            db.close()

        yield f"\n[{datetime.now().strftime('%H:%M:%S')}] === PASO 2/2: Sincronizar Publications (API ML) ===\n"

        # Paso 2: Sync publications incremental (activas)
        db2 = SessionLocal()
        try:
            sys.stdout = log_buffer
            await sync_ml_publications_incremental(db2)
            sys.stdout = old_stdout
            output = log_buffer.getvalue()
            yield output
        except Exception as e:
            sys.stdout = old_stdout
            yield f"ERROR en publications: {str(e)}\n"
        finally:
            db2.close()

        yield f"\n[{datetime.now().strftime('%H:%M:%S')}] === SINCRONIZACIÓN COMPLETA ===\n"

    return StreamingResponse(generate_log(), media_type="text/plain")
