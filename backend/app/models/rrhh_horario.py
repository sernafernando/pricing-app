"""
Configuración de horarios y excepciones — Phase 7.

Define turnos de trabajo (3 configurados: 8-17, 9-18, part-time)
y excepciones (feriados, días especiales).

Los empleados se asignan a un horario. Las fichadas se comparan contra
el horario para detectar tardanzas (tolerancia configurable).
Home office: mismas reglas de horario aplican, pero sin fichada Hikvision.
"""

from sqlalchemy import (
    Boolean,
    Column,
    Date,
    DateTime,
    Integer,
    String,
    Time,
)
from sqlalchemy.sql import func

from app.core.database import Base


class RRHHHorarioConfig(Base):
    """Definición de turno/horario de trabajo."""

    __tablename__ = "rrhh_horarios_config"

    id = Column(Integer, primary_key=True, index=True)
    nombre = Column(String(100), unique=True, nullable=False)  # "Turno Mañana"
    hora_entrada = Column(Time, nullable=False)
    hora_salida = Column(Time, nullable=False)
    tolerancia_minutos = Column(Integer, nullable=False, default=15)
    dias_semana = Column(
        String(20), nullable=False, default="1,2,3,4,5"
    )  # 1=Lun ... 7=Dom
    activo = Column(Boolean, nullable=False, default=True)
    created_at = Column(DateTime(timezone=True), server_default=func.now())

    def __repr__(self) -> str:
        return (
            f"<RRHHHorarioConfig(nombre='{self.nombre}', "
            f"{self.hora_entrada}-{self.hora_salida})>"
        )


class RRHHHorarioExcepcion(Base):
    """Feriado o día especial que afecta los horarios."""

    __tablename__ = "rrhh_horarios_excepciones"

    id = Column(Integer, primary_key=True, index=True)
    fecha = Column(Date, nullable=False, unique=True, index=True)
    tipo = Column(String(30), nullable=False)  # feriado, dia_especial
    descripcion = Column(String(255), nullable=False)  # "Día del Trabajador"
    es_laborable = Column(
        Boolean, nullable=False, default=False
    )  # True si se trabaja igual
    created_at = Column(DateTime(timezone=True), server_default=func.now())

    def __repr__(self) -> str:
        return (
            f"<RRHHHorarioExcepcion(fecha='{self.fecha}', "
            f"tipo='{self.tipo}', desc='{self.descripcion}')>"
        )
