"""
Log de actividad de operadores — trazabilidad completa.

Registra TODA acción que hace un operador identificado con PIN:
upload de ZPL, pistoleado, borrado de etiquetas, asignación de logística, etc.
"""

from sqlalchemy import Column, Integer, String, DateTime, ForeignKey, Index, Text
from sqlalchemy.dialects.postgresql import JSONB
from sqlalchemy.sql import func
from sqlalchemy.orm import relationship
from app.core.database import Base


class OperadorActividad(Base):
    """Log de actividad de un operador en el sistema."""

    __tablename__ = "operador_actividad"

    id = Column(Integer, primary_key=True, index=True)
    operador_id = Column(Integer, ForeignKey("operadores.id"), nullable=False)
    usuario_id = Column(Integer, nullable=False)  # sesión del sistema (user logueado)
    tab_key = Column(String(50), nullable=False)  # ej: 'envios-flex'
    accion = Column(String(100), nullable=False)  # ej: 'upload_zpl', 'borrar_etiquetas', 'pistoleado'
    detalle = Column(JSONB, nullable=True)  # datos específicos de la acción
    created_at = Column(DateTime(timezone=True), server_default=func.now())

    # Relationships
    operador = relationship("Operador", lazy="joined")

    __table_args__ = (
        Index("idx_actividad_operador", "operador_id"),
        Index("idx_actividad_created", "created_at"),
        Index("idx_actividad_accion", "accion"),
        Index("idx_actividad_tab", "tab_key"),
    )

    def __repr__(self) -> str:
        return f"<OperadorActividad(operador={self.operador_id}, accion={self.accion})>"
