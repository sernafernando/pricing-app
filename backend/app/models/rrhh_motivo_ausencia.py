"""
Motivos de ausencia configurables para presentismo.

RRHH define qué motivos de ausencia existen (enfermedad, trámite personal,
familiar enfermo, sin aviso, etc.).
Se administra desde el panel de configuración — no está hardcodeado.
"""

from sqlalchemy import Column, DateTime, Integer, String, Boolean
from sqlalchemy.sql import func

from app.core.database import Base


class RRHHMotivoAusencia(Base):
    """Motivo de ausencia de un empleado (configurable por RRHH)."""

    __tablename__ = "rrhh_motivo_ausencia"

    id = Column(Integer, primary_key=True, index=True)
    nombre = Column(String(100), unique=True, nullable=False)
    descripcion = Column(String(500), nullable=True)
    activo = Column(Boolean, nullable=False, default=True)
    orden = Column(Integer, nullable=False, default=0)
    created_at = Column(DateTime(timezone=True), server_default=func.now())

    def __repr__(self) -> str:
        return f"<RRHHMotivoAusencia(nombre='{self.nombre}')>"
