"""
Tipos de documento configurables para legajos de empleados.

RRHH define qué documentos necesita de cada empleado (DNI frente/dorso,
CUIL, certificado de domicilio, contrato laboral, etc.).
No está hardcodeado — se administra desde el panel de configuración.
"""

from sqlalchemy import Column, Integer, String, Boolean, DateTime
from sqlalchemy.sql import func
from app.core.database import Base


class RRHHTipoDocumento(Base):
    """
    Tipo de documento que un empleado puede/debe tener en su legajo.

    - requiere_vencimiento: si True, el documento tiene fecha de vencimiento
      (ej: certificado de domicilio se renueva cada 6 meses).
    """

    __tablename__ = "rrhh_tipo_documento"

    id = Column(Integer, primary_key=True, index=True)
    nombre = Column(String(100), unique=True, nullable=False)
    descripcion = Column(String(500), nullable=True)
    requiere_vencimiento = Column(Boolean, nullable=False, default=False)
    activo = Column(Boolean, nullable=False, default=True)
    orden = Column(Integer, nullable=False, default=0)
    created_at = Column(DateTime(timezone=True), server_default=func.now())

    def __repr__(self) -> str:
        return f"<RRHHTipoDocumento(nombre='{self.nombre}')>"
