"""
Vacaciones — módulo RRHH.

Dos entidades:
- RRHHVacacionesPeriodo: período anual por empleado con días correspondientes
  según Ley 20.744 art 150 (antigüedad al 31/dic del año).
- RRHHVacacionesSolicitud: solicitud de vacaciones contra un período,
  con flujo pendiente → aprobada/rechazada → gozada/cancelada.
"""

import enum
from sqlalchemy import (
    Column,
    Integer,
    String,
    Date,
    DateTime,
    Text,
    ForeignKey,
    UniqueConstraint,
    Index,
)
from sqlalchemy.orm import relationship
from sqlalchemy.sql import func
from app.core.database import Base


class EstadoSolicitudVacaciones(str, enum.Enum):
    PENDIENTE = "pendiente"
    APROBADA = "aprobada"
    RECHAZADA = "rechazada"
    CANCELADA = "cancelada"
    GOZADA = "gozada"


class RRHHVacacionesPeriodo(Base):
    """
    Período anual de vacaciones por empleado.

    Ley 20.744 art 150 — días según antigüedad al 31/dic del año:
    - < 5 años  → 14 días corridos
    - 5-10 años → 21 días corridos
    - 10-20 años → 28 días corridos
    - > 20 años  → 35 días corridos
    """

    __tablename__ = "rrhh_vacaciones_periodo"

    id = Column(Integer, primary_key=True, index=True)
    empleado_id = Column(
        Integer,
        ForeignKey("rrhh_empleados.id", ondelete="CASCADE"),
        nullable=False,
        index=True,
    )
    anio = Column(Integer, nullable=False)
    dias_correspondientes = Column(Integer, nullable=False)  # 14, 21, 28, or 35
    dias_gozados = Column(Integer, nullable=False, default=0)
    dias_pendientes = Column(Integer, nullable=False)  # correspondientes - gozados
    antiguedad_anios = Column(Integer, nullable=False)  # at Dec 31 of anio

    created_at = Column(DateTime(timezone=True), server_default=func.now())
    updated_at = Column(DateTime(timezone=True), onupdate=func.now())

    # --- Relaciones ---
    empleado = relationship("RRHHEmpleado")
    solicitudes = relationship("RRHHVacacionesSolicitud", back_populates="periodo")

    __table_args__ = (UniqueConstraint("empleado_id", "anio", name="uq_vacaciones_periodo_empleado_anio"),)

    def __repr__(self) -> str:
        return (
            f"<RRHHVacacionesPeriodo(empleado_id={self.empleado_id}, "
            f"anio={self.anio}, dias={self.dias_correspondientes})>"
        )


class RRHHVacacionesSolicitud(Base):
    """
    Solicitud de vacaciones contra un período.

    Flujo de estados:
    - pendiente → aprobada | rechazada
    - aprobada → gozada | cancelada
    - cancelada restaura días al período si estaba aprobada.
    """

    __tablename__ = "rrhh_vacaciones_solicitud"

    id = Column(Integer, primary_key=True, index=True)
    empleado_id = Column(
        Integer,
        ForeignKey("rrhh_empleados.id", ondelete="CASCADE"),
        nullable=False,
        index=True,
    )
    periodo_id = Column(
        Integer,
        ForeignKey("rrhh_vacaciones_periodo.id", ondelete="CASCADE"),
        nullable=False,
        index=True,
    )
    fecha_desde = Column(Date, nullable=False)
    fecha_hasta = Column(Date, nullable=False)
    dias_solicitados = Column(Integer, nullable=False)
    estado = Column(String(20), nullable=False, default="pendiente", index=True)
    motivo_rechazo = Column(Text, nullable=True)

    # Approval
    aprobada_por_id = Column(Integer, ForeignKey("usuarios.id"), nullable=True)
    aprobada_at = Column(DateTime(timezone=True), nullable=True)

    # Audit
    solicitada_por_id = Column(Integer, ForeignKey("usuarios.id"), nullable=False)
    created_at = Column(DateTime(timezone=True), server_default=func.now())
    updated_at = Column(DateTime(timezone=True), onupdate=func.now())

    # --- Relaciones ---
    empleado = relationship("RRHHEmpleado")
    periodo = relationship("RRHHVacacionesPeriodo", back_populates="solicitudes")
    aprobada_por = relationship("Usuario", foreign_keys=[aprobada_por_id])
    solicitada_por = relationship("Usuario", foreign_keys=[solicitada_por_id])

    __table_args__ = (Index("idx_vacaciones_solicitud_estado", "empleado_id", "estado"),)

    def __repr__(self) -> str:
        return (
            f"<RRHHVacacionesSolicitud(id={self.id}, "
            f"empleado_id={self.empleado_id}, "
            f"{self.fecha_desde} - {self.fecha_hasta}, "
            f"estado={self.estado})>"
        )
