"""
Presentismo diario de empleados — módulo RRHH.

Cada fila representa el estado de asistencia de UN empleado en UN día.
El constraint UNIQUE (empleado_id, fecha) garantiza una sola entrada
por persona por día.

Estados posibles: presente, ausente, home_office, vacaciones, art, licencia, franco, feriado.

Si el estado es 'art', se puede vincular al caso ART correspondiente
mediante art_caso_id (FK opcional).
"""

import enum
from sqlalchemy import (
    Column,
    Integer,
    String,
    Date,
    DateTime,
    Time,
    Text,
    ForeignKey,
    Index,
    UniqueConstraint,
)
from sqlalchemy.orm import relationship
from sqlalchemy.sql import func
from app.core.database import Base


class EstadoPresentismo(str, enum.Enum):
    PRESENTE = "presente"
    AUSENTE = "ausente"
    HOME_OFFICE = "home_office"
    VACACIONES = "vacaciones"
    ART = "art"
    LICENCIA = "licencia"
    FRANCO = "franco"
    FERIADO = "feriado"


class RRHHPresentismoDiario(Base):
    """
    Una fila por empleado por día.

    - estado: uno de EstadoPresentismo (almacenado como string, no PG enum).
    - hora_ingreso / hora_egreso: opcionales, para registro manual básico.
    - art_caso_id: link opcional al caso ART cuando estado='art'.
    """

    __tablename__ = "rrhh_presentismo_diario"

    id = Column(Integer, primary_key=True, index=True)
    empleado_id = Column(
        Integer,
        ForeignKey("rrhh_empleados.id", ondelete="CASCADE"),
        nullable=False,
        index=True,
    )
    fecha = Column(Date, nullable=False, index=True)
    estado = Column(String(30), nullable=False, default="presente")
    hora_ingreso = Column(Time, nullable=True)
    hora_egreso = Column(Time, nullable=True)
    observaciones = Column(Text, nullable=True)

    # ART reference (if estado='art')
    art_caso_id = Column(
        Integer,
        ForeignKey("rrhh_art_casos.id"),
        nullable=True,
    )

    # Audit
    registrado_por_id = Column(
        Integer,
        ForeignKey("usuarios.id"),
        nullable=True,
    )
    created_at = Column(DateTime(timezone=True), server_default=func.now())
    updated_at = Column(DateTime(timezone=True), onupdate=func.now())

    # --- Relaciones ---
    empleado = relationship("RRHHEmpleado")
    art_caso = relationship("RRHHArtCaso")
    registrado_por = relationship("Usuario")

    __table_args__ = (
        UniqueConstraint("empleado_id", "fecha", name="uq_presentismo_empleado_fecha"),
        Index("idx_presentismo_fecha_estado", "fecha", "estado"),
    )

    def __repr__(self) -> str:
        return f"<RRHHPresentismoDiario(empleado_id={self.empleado_id}, fecha={self.fecha}, estado='{self.estado}')>"
