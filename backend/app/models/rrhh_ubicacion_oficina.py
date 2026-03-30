"""
Ubicaciones de oficina — referencia para cálculo de distancia en fichaje mobile.

Almacena coordenadas de las sedes/oficinas de la empresa. Se usa para
calcular distancia_oficina_metros en las fichadas mobile (informativo,
nunca bloquea el fichaje).
"""

from sqlalchemy import (
    Boolean,
    Column,
    DateTime,
    Float,
    Integer,
    Numeric,
    String,
)
from sqlalchemy.sql import func

from app.core.database import Base


class RRHHUbicacionOficina(Base):
    """Ubicación geográfica de una sede/oficina de la empresa."""

    __tablename__ = "rrhh_ubicaciones_oficina"

    id = Column(Integer, primary_key=True, index=True)
    nombre = Column(String(100), nullable=False)
    latitud = Column(Numeric(10, 8), nullable=False)
    longitud = Column(Numeric(11, 8), nullable=False)
    radio_metros = Column(Float, nullable=False, default=100.0)
    activo = Column(Boolean, nullable=False, default=True, server_default="true")
    created_at = Column(DateTime(timezone=True), server_default=func.now())

    def __repr__(self) -> str:
        return f"<RRHHUbicacionOficina(id={self.id}, nombre='{self.nombre}', lat={self.latitud}, lng={self.longitud})>"
