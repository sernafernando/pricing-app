#!/usr/bin/env python3
"""
Sincronización completa standalone — NO pasa por uvicorn.

Ejecuta directamente los services con su propia sesión de DB,
liberando los workers de uvicorn para requests de usuarios.

Incluye file lock para evitar ejecuciones concurrentes.

Uso:
    cd /var/www/html/pricing-app/backend
    python -m app.scripts.sync_completo

Cron:
    */10 6-21 * * * cd /var/www/html/pricing-app/backend && \
        /var/www/html/pricing-app/backend/venv/bin/python \
        -m app.scripts.sync_completo \
        >> /var/log/pricing-app/pricing-sync.log 2>&1
"""

import asyncio
import fcntl
import os
import sys
from datetime import datetime
from pathlib import Path

# ── Bootstrap: path + .env ──────────────────────────────────────
if __name__ == "__main__":
    backend_path = os.path.dirname(os.path.dirname(os.path.dirname(os.path.abspath(__file__))))
    if backend_path not in sys.path:
        sys.path.insert(0, backend_path)

    from dotenv import load_dotenv

    env_path = Path(backend_path) / ".env"
    load_dotenv(dotenv_path=env_path)

# ── Imports de app (después del bootstrap) ──────────────────────
from app.core.database import SessionLocal  # noqa: E402

LOCK_FILE = "/tmp/pricing-sync-completo.lock"


def log(msg: str) -> None:
    print(f"[{datetime.now().strftime('%Y-%m-%d %H:%M:%S')}] {msg}", flush=True)


def timed(name: str):
    """Context manager para loguear duración de cada paso."""

    class Timer:
        def __enter__(self):
            self.start = datetime.now()
            log(f"Iniciando {name}...")
            return self

        def __exit__(self, exc_type, exc_val, exc_tb):
            elapsed = (datetime.now() - self.start).total_seconds()
            if exc_type:
                log(f"ERROR en {name} ({elapsed:.1f}s): {exc_val}")
            else:
                log(f"OK {name} ({elapsed:.1f}s)")
            return False  # No suppress exceptions

    return Timer()


async def sync_all() -> None:
    log("=== INICIO SINCRONIZACIÓN COMPLETA (standalone) ===")
    start = datetime.now()

    # 1. Tipo de cambio
    with timed("Tipo de cambio"):
        try:
            from app.services.tipo_cambio_service import actualizar_tipo_cambio_bna

            db = SessionLocal()
            try:
                result = actualizar_tipo_cambio_bna(db)
                log(f"  Tipo cambio: {result}")
            finally:
                db.close()
        except Exception as e:
            log(f"  Error tipo cambio: {e}")

    # 2. Sync ERP (productos + precios ML)
    with timed("ERP + Precios ML"):
        try:
            from app.services.erp_sync import sincronizar_erp
            from app.services.sync_precios_ml import sincronizar_precios_ml

            db = SessionLocal()
            try:
                resultado_erp = await sincronizar_erp(db)
                log(f"  ERP: {resultado_erp}")

                resultado_precios = sincronizar_precios_ml(db)
                log(f"  Precios ML: {resultado_precios}")
            finally:
                db.close()
        except Exception as e:
            log(f"  Error ERP: {e}")

    # 3. Publicaciones ML
    with timed("Publicaciones ML"):
        try:
            from app.services.ml_sync import sincronizar_publicaciones_ml

            db = SessionLocal()
            try:
                resultado_ml = await sincronizar_publicaciones_ml(db)
                log(f"  ML: {resultado_ml}")
            finally:
                db.close()
        except Exception as e:
            log(f"  Error ML: {e}")

    # 4. Ofertas Sheets
    with timed("Ofertas Sheets"):
        try:
            from app.services.google_sheets_sync import sincronizar_ofertas_sheets

            db = SessionLocal()
            try:
                resultado_sheets = sincronizar_ofertas_sheets(db)
                log(f"  Sheets: {resultado_sheets}")
            finally:
                db.close()
        except Exception as e:
            log(f"  Error Sheets: {e}")

    # 5. Recalcular markups
    with timed("Recalcular markups"):
        try:
            from app.services.recalcular_markups_service import recalcular_markups

            db = SessionLocal()
            try:
                resultado_markups = recalcular_markups(db)
                log(f"  Markups: {resultado_markups}")
            finally:
                db.close()
        except Exception as e:
            log(f"  Error markups: {e}")

    elapsed = (datetime.now() - start).total_seconds()
    log(f"=== FIN SINCRONIZACIÓN COMPLETA ({elapsed:.1f}s) ===")


def main() -> None:
    """Entry point con file lock para evitar ejecuciones concurrentes."""
    lock_fd = open(LOCK_FILE, "w")
    try:
        fcntl.flock(lock_fd, fcntl.LOCK_EX | fcntl.LOCK_NB)
    except OSError:
        log("SKIP: otra instancia de sync_completo ya está corriendo")
        sys.exit(0)

    try:
        lock_fd.write(str(os.getpid()))
        lock_fd.flush()
        asyncio.run(sync_all())
    except KeyboardInterrupt:
        log("Sincronización interrumpida por el usuario")
        sys.exit(130)
    except Exception as e:
        log(f"Error crítico: {e}")
        sys.exit(1)
    finally:
        fcntl.flock(lock_fd, fcntl.LOCK_UN)
        lock_fd.close()


if __name__ == "__main__":
    main()
