"""
Sanciones disciplinarias — módulo RRHH.

Tipos de sanción configurables (RRHHTipoSancion):
- Apercibimiento, suspensión 1 día, suspensión 3 días, etc.
- Cada tipo define si requiere descuento salarial y cantidad de días.

Cada sanción (RRHHSancion) se vincula a un empleado con motivo, fechas
de vigencia, y posibilidad de anulación con motivo documentado.
"""

from sqlalchemy import (
    Column,
    Integer,
    String,
    Date,
    DateTime,
    Boolean,
    Text,
    ForeignKey,
    Index,
)
from sqlalchemy.orm import relationship
from sqlalchemy.sql import func
from app.core.database import Base


class RRHHTipoSancion(Base):
    """Tipos configurables: apercibimiento, suspensión 1 día, etc."""

    __tablename__ = "rrhh_tipo_sancion"

    id = Column(Integer, primary_key=True, index=True)
    nombre = Column(String(100), unique=True, nullable=False)
    descripcion = Column(String(500), nullable=True)
    dias_suspension = Column(Integer, nullable=True)  # NULL for apercibimiento
    requiere_descuento = Column(Boolean, nullable=False, default=False)
    activo = Column(Boolean, nullable=False, default=True)
    orden = Column(Integer, nullable=False, default=0)
    created_at = Column(DateTime(timezone=True), server_default=func.now())

    def __repr__(self) -> str:
        return f"<RRHHTipoSancion(nombre='{self.nombre}')>"


class RRHHSancion(Base):
    """
    Sanción aplicada a un empleado.

    - anulada: si es True, la sanción fue dejada sin efecto.
    - fecha_desde / fecha_hasta: período de suspensión (si aplica).
    """

    __tablename__ = "rrhh_sanciones"

    id = Column(Integer, primary_key=True, index=True)
    empleado_id = Column(
        Integer,
        ForeignKey("rrhh_empleados.id", ondelete="CASCADE"),
        nullable=False,
        index=True,
    )
    tipo_sancion_id = Column(
        Integer,
        ForeignKey("rrhh_tipo_sancion.id"),
        nullable=False,
        index=True,
    )
    fecha = Column(Date, nullable=False, index=True)
    motivo = Column(Text, nullable=False)
    descripcion = Column(Text, nullable=True)
    fecha_desde = Column(Date, nullable=True)  # suspension start
    fecha_hasta = Column(Date, nullable=True)  # suspension end

    # Anulación
    anulada = Column(Boolean, nullable=False, default=False)
    anulada_motivo = Column(Text, nullable=True)
    anulada_por_id = Column(Integer, ForeignKey("usuarios.id"), nullable=True)
    anulada_at = Column(DateTime(timezone=True), nullable=True)

    # Audit
    aplicada_por_id = Column(Integer, ForeignKey("usuarios.id"), nullable=False)
    created_at = Column(DateTime(timezone=True), server_default=func.now())

    # --- Relaciones ---
    empleado = relationship("RRHHEmpleado")
    tipo_sancion = relationship("RRHHTipoSancion")
    aplicada_por = relationship("Usuario", foreign_keys=[aplicada_por_id])
    anulada_por = relationship("Usuario", foreign_keys=[anulada_por_id])

    __table_args__ = (Index("idx_sanciones_empleado_fecha", "empleado_id", "fecha"),)

    def __repr__(self) -> str:
        return f"<RRHHSancion(id={self.id}, empleado_id={self.empleado_id}, fecha={self.fecha})>"
