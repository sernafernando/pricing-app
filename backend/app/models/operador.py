"""
Operadores de depósito — sistema de micro-usuarios con PIN de 4 dígitos.

Los operadores se identifican con un PIN único al entrar a tabs que requieren
trazabilidad (ej: Envíos Flex, Pistoleado). El PIN tiene timeout de inactividad
configurable por tab. Todas las acciones se logean en operador_actividad.
"""

from sqlalchemy import Column, Integer, String, Boolean, DateTime, Index
from sqlalchemy.sql import func
from app.core.database import Base


class Operador(Base):
    """Operador de depósito con PIN de 4 dígitos."""

    __tablename__ = "operadores"

    id = Column(Integer, primary_key=True, index=True)
    pin = Column(String(4), unique=True, nullable=False)
    nombre = Column(String(100), nullable=False)
    activo = Column(Boolean, default=True, nullable=False)
    created_at = Column(DateTime(timezone=True), server_default=func.now())

    __table_args__ = (Index("idx_operadores_pin", "pin", unique=True),)

    def __repr__(self) -> str:
        return f"<Operador(id={self.id}, nombre={self.nombre}, pin={self.pin})>"
