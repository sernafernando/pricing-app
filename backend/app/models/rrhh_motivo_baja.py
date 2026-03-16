"""
Motivos de baja configurables para empleados.

RRHH define qué motivos de baja existen (renuncia, despido, jubilación, etc.).
Se administra desde el panel de configuración — no está hardcodeado.
"""

from sqlalchemy import Column, DateTime, Integer, String, Boolean
from sqlalchemy.sql import func

from app.core.database import Base


class RRHHMotivoBaja(Base):
    """Motivo de baja de un empleado (configurable por RRHH)."""

    __tablename__ = "rrhh_motivo_baja"

    id = Column(Integer, primary_key=True, index=True)
    nombre = Column(String(100), unique=True, nullable=False)
    descripcion = Column(String(500), nullable=True)
    requiere_documentacion = Column(Boolean, nullable=False, default=False)
    activo = Column(Boolean, nullable=False, default=True)
    orden = Column(Integer, nullable=False, default=0)
    created_at = Column(DateTime(timezone=True), server_default=func.now())

    def __repr__(self) -> str:
        return f"<RRHHMotivoBaja(nombre='{self.nombre}')>"
