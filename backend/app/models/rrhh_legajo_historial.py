"""
Historial de cambios del legajo de empleados.

Registra cada modificación a los datos de un empleado.
Permite auditoría completa: quién cambió qué, cuándo, y de qué valor a cuál.

Sigue el mismo patrón que rma_caso_historial.py.
"""

from sqlalchemy import Column, Integer, String, DateTime, Text, ForeignKey
from sqlalchemy.orm import relationship
from sqlalchemy.sql import func
from app.core.database import Base


class RRHHLegajoHistorial(Base):
    """
    Log de auditoría para cambios en legajos de empleados.

    Cada fila = un campo que cambió. Si se modifican 3 campos en una
    misma operación, se crean 3 filas con el mismo timestamp aproximado.
    """

    __tablename__ = "rrhh_legajo_historial"

    id = Column(Integer, primary_key=True, index=True)

    # Referencia al empleado
    empleado_id = Column(
        Integer,
        ForeignKey("rrhh_empleados.id", ondelete="CASCADE"),
        nullable=False,
        index=True,
    )

    # Qué campo cambió
    campo = Column(String(100), nullable=False)

    # Valores antes y después (como texto para soportar cualquier tipo)
    valor_anterior = Column(Text, nullable=True)
    valor_nuevo = Column(Text, nullable=True)

    # Quién hizo el cambio
    usuario_id = Column(Integer, ForeignKey("usuarios.id"), nullable=False, index=True)

    # Cuándo
    created_at = Column(DateTime(timezone=True), server_default=func.now())

    # --- Relaciones ---
    empleado = relationship("RRHHEmpleado", back_populates="historial")
    usuario = relationship("Usuario")

    def __repr__(self) -> str:
        return f"<RRHHLegajoHistorial(id={self.id}, empleado_id={self.empleado_id}, campo='{self.campo}')>"
