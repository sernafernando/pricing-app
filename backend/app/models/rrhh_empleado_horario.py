"""
Asignación de turnos/horarios a empleados — tabla intermedia many-to-many.

Un empleado puede tener múltiples turnos (ej: Lunes-Viernes 8-17 + Sábado 8-12).
Cada turno ya define sus dias_semana en RRHHHorarioConfig, por lo que la relación
es directa: empleado_id + horario_config_id.

El campo prioridad permite ordenar turnos del empleado (menor = principal).
"""

from sqlalchemy import Column, DateTime, ForeignKey, Integer, UniqueConstraint
from sqlalchemy.orm import relationship
from sqlalchemy.sql import func

from app.core.database import Base


class RRHHEmpleadoHorario(Base):
    """Asignación de un turno/horario a un empleado."""

    __tablename__ = "rrhh_empleado_horarios"

    id = Column(Integer, primary_key=True, index=True)
    empleado_id = Column(
        Integer,
        ForeignKey("rrhh_empleados.id", ondelete="CASCADE"),
        nullable=False,
        index=True,
    )
    horario_config_id = Column(
        Integer,
        ForeignKey("rrhh_horarios_config.id", ondelete="CASCADE"),
        nullable=False,
        index=True,
    )
    prioridad = Column(Integer, nullable=False, default=1)
    created_at = Column(DateTime(timezone=True), server_default=func.now())

    # --- Relaciones ---
    empleado = relationship("RRHHEmpleado", backref="horarios_asignados")
    horario_config = relationship("RRHHHorarioConfig")

    __table_args__ = (
        UniqueConstraint(
            "empleado_id",
            "horario_config_id",
            name="uq_empleado_horario",
        ),
    )

    def __repr__(self) -> str:
        return (
            f"<RRHHEmpleadoHorario(empleado_id={self.empleado_id}, "
            f"horario_config_id={self.horario_config_id}, prioridad={self.prioridad})>"
        )
