import asyncio
import sys
from datetime import datetime

from fastapi import APIRouter, Depends, BackgroundTasks
from fastapi.responses import StreamingResponse
from sqlalchemy.orm import Session
from app.core.database import get_db, SessionLocal
from app.services.sync_precios_ml import sincronizar_precios_ml, PRICELISTS
from app.api.deps import get_current_user

router = APIRouter()


class QueueWriter:
    """
    Reemplaza sys.stdout para capturar print() y enviar cada línea
    a un asyncio.Queue en tiempo real. Esto permite que el StreamingResponse
    yieldee progreso mientras las funciones de sync están corriendo.

    Funciona porque las funciones de sync corren como asyncio tasks en el mismo
    event loop, así que put_nowait es seguro (mismo thread).
    """

    def __init__(self, queue: asyncio.Queue):
        self._queue = queue

    def write(self, text: str) -> int:
        if text:
            self._queue.put_nowait(text)
        return len(text) if text else 0

    def flush(self) -> None:
        pass


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
    Usa asyncio.Queue + QueueWriter para capturar print() en tiempo real
    y streamear el progreso al frontend línea por línea.
    """
    from app.scripts.sync_ml_items_publicados_full import sync_items_publicados_full
    from app.scripts.sync_ml_publications_incremental import sync_ml_publications_incremental

    queue: asyncio.Queue = asyncio.Queue()

    async def run_sync():
        """Corre ambas funciones de sync con stdout redirigido a la queue."""
        old_stdout = sys.stdout
        writer = QueueWriter(queue)
        sys.stdout = writer

        try:
            # Paso 1: Sync items publicados desde GBP
            print(f"[{datetime.now().strftime('%H:%M:%S')}] === PASO 1/2: Sincronizar Items Publicados (GBP) ===")
            db = SessionLocal()
            try:
                await sync_items_publicados_full(db)
            except Exception as e:
                print(f"ERROR en items publicados: {e}")
            finally:
                db.close()

            # Paso 2: Sync publications incremental (API ML)
            print(f"\n[{datetime.now().strftime('%H:%M:%S')}] === PASO 2/2: Sincronizar Publications (API ML) ===")
            db2 = SessionLocal()
            try:
                await sync_ml_publications_incremental(db2)
            except Exception as e:
                print(f"ERROR en publications: {e}")
            finally:
                db2.close()

            print(f"\n[{datetime.now().strftime('%H:%M:%S')}] === SINCRONIZACIÓN COMPLETA ===")
        finally:
            sys.stdout = old_stdout
            # Señal de fin: None indica que no hay más output
            await queue.put(None)

    async def generate_log():
        """Generador que pollea la queue y yieldea cada chunk al frontend."""
        # Lanzar la tarea de sync en paralelo
        task = asyncio.create_task(run_sync())

        try:
            while True:
                # Esperar hasta 1 segundo por nuevo output
                try:
                    chunk = await asyncio.wait_for(queue.get(), timeout=1.0)
                except asyncio.TimeoutError:
                    # No hay output nuevo, pero la tarea sigue corriendo.
                    # Yieldear string vacío para mantener la conexión viva.
                    if task.done():
                        break
                    continue

                if chunk is None:
                    # Señal de fin
                    break

                yield chunk
        finally:
            # Asegurar que la tarea termine si el cliente se desconecta
            if not task.done():
                task.cancel()
                try:
                    await task
                except asyncio.CancelledError:
                    pass

    return StreamingResponse(generate_log(), media_type="text/plain")
