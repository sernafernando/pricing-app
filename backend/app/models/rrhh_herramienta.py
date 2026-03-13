"""
Asignación de herramientas a empleados — Phase 6.

Registra herramientas/equipamiento de trabajo asignado a cada empleado.
Tracking de estado: asignado, devuelto, perdido, roto.
Separado de compras (cuenta corriente) — esto es equipamiento de la empresa.
"""

from sqlalchemy import (
    Column,
    Integer,
    String,
    Date,
    DateTime,
    Text,
    ForeignKey,
    Index,
)
from sqlalchemy.orm import relationship
from sqlalchemy.sql import func
from app.core.database import Base


class RRHHAsignacionHerramienta(Base):
    """Herramienta o equipamiento asignado a un empleado."""

    __tablename__ = "rrhh_asignacion_herramienta"

    id = Column(Integer, primary_key=True, index=True)
    empleado_id = Column(
        Integer,
        ForeignKey("rrhh_empleados.id", ondelete="CASCADE"),
        nullable=False,
        index=True,
    )
    descripcion = Column(String(255), nullable=False)  # "Notebook Lenovo T14"
    codigo_inventario = Column(String(100), nullable=True)  # código ERP / interno
    item_id = Column(Integer, nullable=True)  # FK conceptual a tb_item (ERP)
    cantidad = Column(Integer, nullable=False, default=1)
    fecha_asignacion = Column(Date, nullable=False)
    fecha_devolucion = Column(Date, nullable=True)
    estado = Column(String(30), nullable=False, default="asignado")  # asignado, devuelto, perdido, roto
    observaciones = Column(Text, nullable=True)

    # --- Auditoría ---
    asignado_por_id = Column(Integer, ForeignKey("usuarios.id"), nullable=False)
    created_at = Column(DateTime(timezone=True), server_default=func.now())
    updated_at = Column(DateTime(timezone=True), onupdate=func.now())

    # --- Relaciones ---
    empleado = relationship("RRHHEmpleado")
    asignado_por = relationship("Usuario")

    __table_args__ = (Index("idx_herramientas_empleado_estado", "empleado_id", "estado"),)

    def __repr__(self) -> str:
        return (
            f"<RRHHAsignacionHerramienta(id={self.id}, "
            f"empleado_id={self.empleado_id}, "
            f"descripcion='{self.descripcion}')>"
        )
