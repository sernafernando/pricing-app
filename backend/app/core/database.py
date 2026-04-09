import sys
from contextlib import contextmanager
from typing import Generator

from sqlalchemy import create_engine
from sqlalchemy.orm import Session, declarative_base, sessionmaker
from sqlalchemy.pool import NullPool

from app.core.config import settings


def _is_script_context() -> bool:
    """
    Detecta si estamos corriendo como script de cron/CLI (python -m app.scripts.*)
    o como servidor FastAPI (uvicorn).

    Scripts → NullPool (1 conexión, sin pool persistente)
    FastAPI → QueuePool (pool de conexiones reutilizables)
    """
    main_module = sys.modules.get("__main__")
    if main_module is None:
        return False
    main_file = getattr(main_module, "__file__", "") or ""
    # Scripts corren desde app/scripts/ o scripts/
    return "/scripts/" in main_file or main_file.endswith("alembic/env.py")


# ──────────────────────────────────────────────
# Engine — automáticamente NullPool para scripts
# ──────────────────────────────────────────────
if _is_script_context():
    # Scripts/cron: NullPool = 1 conexión por sesión, se cierra al terminar.
    # Si 10 scripts corren simultáneamente → 10 conexiones (no 10 pools de 10).
    engine = create_engine(
        settings.DATABASE_URL,
        poolclass=NullPool,
    )
else:
    # FastAPI/uvicorn: pool de conexiones reutilizables.
    # pool_size=10       → 10 conexiones persistentes por worker
    # max_overflow=10    → hasta 20 total por worker en picos
    # pool_recycle=900   → recicla cada 15 min (evita stale connections por pg timeout)
    # pool_timeout=30    → espera 30s antes de fallar (20s era agresivo en picos)
    # pool_pre_ping=True → verifica que la conexión siga viva antes de usarla
    #
    # Con 4 workers: 4 × 20 = 80 conexiones worst-case (PostgreSQL max_connections=150)
    engine = create_engine(
        settings.DATABASE_URL,
        pool_pre_ping=True,
        pool_size=10,
        max_overflow=10,
        pool_recycle=900,
        pool_timeout=30,
    )

SessionLocal = sessionmaker(autocommit=False, autoflush=False, bind=engine)

Base = declarative_base()


# Dependency para FastAPI (generator — requires DI to call __next__)
def get_db():
    db = SessionLocal()
    try:
        yield db
    finally:
        db.close()


@contextmanager
def get_background_db() -> Generator[Session, None, None]:
    """
    Context manager para código que corre FUERA del ciclo request/response
    de FastAPI: background tasks, servicios standalone, helpers internos.

    A diferencia de get_db() (generator para DI), este es un @contextmanager
    que garantiza enter/exit eager — no depende de FastAPI para cerrar la sesión.

    Uso:
        with get_background_db() as db:
            db.query(...)
            db.commit()  # commit explícito si se necesita

    Comportamiento:
        - yield Session
        - on success: commit + close
        - on exception: rollback + close + re-raise
    """
    db = SessionLocal()
    try:
        yield db
        db.commit()
    except Exception:
        db.rollback()
        raise
    finally:
        db.close()


# ── ML Webhook DB (ml_previews, read-only) ─────────────────────
_mlwebhook_engine = None


def get_mlwebhook_engine():
    """
    Devuelve un Engine lazy-inicializado para la BD mlwebhook.

    Se usa para leer ml_previews directamente (re-enrichment, catalog sync).
    Falla explícitamente si ML_WEBHOOK_DB_URL no está configurada.
    """
    global _mlwebhook_engine
    if _mlwebhook_engine is None:
        url = settings.ML_WEBHOOK_DB_URL
        if not url:
            raise RuntimeError("ML_WEBHOOK_DB_URL no está configurada en .env. Se necesita para acceder a ml_previews.")
        if _is_script_context():
            _mlwebhook_engine = create_engine(url, poolclass=NullPool)
        else:
            _mlwebhook_engine = create_engine(
                url,
                pool_pre_ping=True,
                pool_size=3,
                max_overflow=2,
                pool_recycle=1800,
                pool_timeout=10,
            )
    return _mlwebhook_engine
