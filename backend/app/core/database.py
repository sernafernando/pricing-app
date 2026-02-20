from sqlalchemy import create_engine
from sqlalchemy.orm import declarative_base, sessionmaker
from app.core.config import settings

engine = create_engine(settings.DATABASE_URL, pool_pre_ping=True, pool_size=10, max_overflow=20)

SessionLocal = sessionmaker(autocommit=False, autoflush=False, bind=engine)

Base = declarative_base()


# Dependency para FastAPI
def get_db():
    db = SessionLocal()
    try:
        yield db
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
        _mlwebhook_engine = create_engine(url, pool_pre_ping=True, pool_size=3, max_overflow=5)
    return _mlwebhook_engine
