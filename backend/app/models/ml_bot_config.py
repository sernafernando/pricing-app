"""
ORM model for `ml_bot_config` — business-knowledge/runtime tuning variables for
the ML questions bot. Mirrors `app/models/configuracion.py`'s clave/valor shape
(design §3/§11), but is bot-scoped with its own `ml_bot.config` permission.
"""

from sqlalchemy import Column, DateTime, String, Text
from sqlalchemy.sql import func

from app.core.database import Base


class MlBotConfig(Base):
    """Single clave/valor row of bot runtime configuration (no redeploy needed)."""

    __tablename__ = "ml_bot_config"

    clave = Column(String(100), primary_key=True)
    valor = Column(Text, nullable=False)
    descripcion = Column(Text, nullable=True)
    tipo = Column(String(50), default="string", server_default="string")
    fecha_modificacion = Column(DateTime(timezone=True), server_default=func.now(), onupdate=func.now())

    def __repr__(self) -> str:
        return f"<MlBotConfig(clave={self.clave}, tipo={self.tipo})>"
