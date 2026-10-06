"""Official-store display names, administrable from the Admin panel.

Keyed by MercadoLibre's `official_store_id` (the value stored in
`mlp_official_store_id`). Display data only: nothing joins to it, an id that
is not here is rendered as "Tienda <id>" by the callers.
"""

from sqlalchemy import BigInteger, Boolean, Column, DateTime, Integer, String
from sqlalchemy.sql import func

from app.core.database import Base


class MlTiendaOficial(Base):
    """One MercadoLibre official store and how the app names it."""

    __tablename__ = "ml_tiendas_oficiales"

    store_id = Column(BigInteger, primary_key=True, autoincrement=False)
    nombre = Column(String(100), nullable=False)
    # Lowercase slug that lets code find "the TP-Link store" without a hardcoded
    # id (e.g. `tplink`). NOT unique: when ML changes a store's id, the old and
    # the new id share one clave so history under the old id keeps counting.
    clave = Column(String(50), nullable=True, index=True)
    orden = Column(Integer, nullable=False, default=0, server_default="0")
    activa = Column(Boolean, nullable=False, default=True, server_default="true")
    created_at = Column(DateTime(timezone=True), nullable=False, server_default=func.now())
    updated_at = Column(DateTime(timezone=True), nullable=False, server_default=func.now(), onupdate=func.now())

    def __repr__(self) -> str:
        return f"<MlTiendaOficial(store_id={self.store_id}, nombre='{self.nombre}')>"
