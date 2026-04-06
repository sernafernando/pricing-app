"""
Empresas propias del grupo — Pastoriza, Grupo Gauss, etc.

Cada empleado pertenece a una empresa. Se usa para diferenciar
cuentas bancarias, razones sociales, y datos fiscales.
Administrable desde el panel de Admin.
"""

from sqlalchemy import Boolean, Column, DateTime, Integer, String, Text
from sqlalchemy.sql import func

from app.core.database import Base


class Empresa(Base):
    """Empresa del grupo (configurable desde Admin)."""

    __tablename__ = "empresas"

    id = Column(Integer, primary_key=True, index=True)
    nombre = Column(String(100), unique=True, nullable=False)
    razon_social = Column(String(255), nullable=True)
    cuit = Column(String(20), nullable=True, unique=True)
    direccion = Column(String(500), nullable=True)
    telefono = Column(String(50), nullable=True)
    email = Column(String(255), nullable=True)
    notas = Column(Text, nullable=True)
    activo = Column(Boolean, nullable=False, default=True)
    orden = Column(Integer, nullable=False, default=0)
    created_at = Column(DateTime(timezone=True), server_default=func.now())
    updated_at = Column(DateTime(timezone=True), onupdate=func.now())

    def __repr__(self) -> str:
        return f"<Empresa(nombre='{self.nombre}')>"
