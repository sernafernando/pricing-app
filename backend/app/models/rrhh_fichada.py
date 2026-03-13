"""
Fichadas (clock-in/out) de empleados — Phase 7.

Registra fichadas de entrada/salida desde el dispositivo Hikvision DS-K1T804AMF
(face + fingerprint) o ingreso manual. Dedup por event_id (serialNo del device).

Mapeo empleado: employeeNoString → hikvision_employee_no → rrhh_empleados.
empleado_id puede ser NULL si el usuario Hikvision aún no fue mapeado.
Al mapear, se actualiza retroactivamente via hikvision_employee_no.
"""

import enum

from sqlalchemy import (
    Column,
    DateTime,
    ForeignKey,
    Index,
    Integer,
    String,
)
from sqlalchemy.orm import relationship
from sqlalchemy.sql import func

from app.core.database import Base


class OrigenFichada(str, enum.Enum):
    HIKVISION = "hikvision"
    MANUAL = "manual"


class TipoFichada(str, enum.Enum):
    ENTRADA = "entrada"
    SALIDA = "salida"


class RRHHFichada(Base):
    """Registro de fichada (clock-in/out) de un empleado."""

    __tablename__ = "rrhh_fichadas"

    id = Column(Integer, primary_key=True, index=True)
    empleado_id = Column(
        Integer,
        ForeignKey("rrhh_empleados.id", ondelete="CASCADE"),
        nullable=True,  # NULL = Hikvision user not yet mapped to employee
        index=True,
    )
    timestamp = Column(DateTime(timezone=True), nullable=False, index=True)
    tipo = Column(String(10), nullable=False)  # entrada / salida
    origen = Column(String(20), nullable=False, default="hikvision")  # hikvision / manual

    # Hikvision-specific
    hikvision_employee_no = Column(
        String(20), nullable=True, index=True
    )  # employeeNoString del dispositivo — para match retroactivo
    device_serial = Column(String(100), nullable=True)
    event_id = Column(String(100), nullable=True, unique=True, index=True)  # dedup key (serialNo)

    # Manual entry
    registrado_por_id = Column(Integer, ForeignKey("usuarios.id"), nullable=True)
    motivo_manual = Column(String(500), nullable=True)

    created_at = Column(DateTime(timezone=True), server_default=func.now())

    # --- Relaciones ---
    empleado = relationship("RRHHEmpleado")
    registrado_por = relationship("Usuario")

    __table_args__ = (Index("idx_fichadas_empleado_timestamp", "empleado_id", "timestamp"),)

    def __repr__(self) -> str:
        return (
            f"<RRHHFichada(id={self.id}, empleado_id={self.empleado_id}, "
            f"tipo='{self.tipo}', timestamp='{self.timestamp}')>"
        )
