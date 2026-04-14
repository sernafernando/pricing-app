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
    # FastAPI/uvicorn: pool moderado — PgBouncer hace el pooling pesado.
    # pool_size=8        → 8 conexiones persistentes por worker a PgBouncer
    # max_overflow=4     → hasta 12 total por worker en picos
    # pool_recycle=600   → recicla cada 10 min (≤ PgBouncer server_idle_timeout)
    # pool_timeout=30    → espera 30s antes de fallar
    # pool_pre_ping=True → detecta conexiones que PgBouncer cerró por idle
    # pool_use_lifo=True → reutiliza la conexión más fresca (menos chance de stale)
    #
    # Con 4 workers: 4 × 12 = 48 client-conns a PgBouncer (max_client_conn=500)
    # PgBouncer → PostgreSQL: ~60-70 conexiones reales (max_connections=200)
    engine = create_engine(
        settings.DATABASE_URL,
        pool_pre_ping=True,
        pool_size=8,
        max_overflow=4,
        pool_recycle=600,
        pool_timeout=30,
        pool_use_lifo=True,
    )

    # Safety net: kill queries running longer than 60s.
    # Can't use connect_args with PgBouncer (transaction mode rejects
    # startup parameters), so we SET it after each connection checkout.
    from sqlalchemy import event

    @event.listens_for(engine, "connect")
    def _set_statement_timeout(dbapi_conn, connection_record):
        cursor = dbapi_conn.cursor()
        cursor.execute("SET statement_timeout = '60s'")
        cursor.close()


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
                pool_size=2,
                max_overflow=2,
                pool_recycle=600,
                pool_timeout=10,
                pool_use_lifo=True,
            )
    return _mlwebhook_engine
