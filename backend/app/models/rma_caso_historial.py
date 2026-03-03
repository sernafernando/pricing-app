"""
Historial de cambios del módulo RMA Seguimiento.

Registra cada modificación a un caso o a un item dentro del caso.
Permite auditoría completa: quién cambió qué, cuándo, y de qué valor a cuál.
"""

from sqlalchemy import Column, Integer, String, DateTime, Text, ForeignKey
from sqlalchemy.orm import relationship
from sqlalchemy.sql import func
from app.core.database import Base


class RmaCasoHistorial(Base):
    """
    Log de auditoría para cambios en casos RMA y sus items.
    """

    __tablename__ = "rma_caso_historial"

    id = Column(Integer, primary_key=True, index=True)

    # Referencia al caso (siempre presente)
    caso_id = Column(Integer, ForeignKey("rma_casos.id", ondelete="CASCADE"), nullable=False, index=True)

    # Referencia al item (NULL si el cambio es a nivel caso)
    caso_item_id = Column(Integer, ForeignKey("rma_caso_items.id", ondelete="CASCADE"), nullable=True, index=True)

    # Qué campo cambió
    campo = Column(String(100), nullable=False)

    # Valores antes y después
    valor_anterior = Column(Text, nullable=True)
    valor_nuevo = Column(Text, nullable=True)

    # Quién hizo el cambio
    usuario_id = Column(Integer, ForeignKey("usuarios.id"), nullable=False, index=True)

    # Cuándo
    created_at = Column(DateTime(timezone=True), server_default=func.now())

    # --- Relaciones ---
    caso = relationship("RmaCaso", back_populates="historial")
    caso_item = relationship("RmaCasoItem")
    usuario = relationship("Usuario")

    def __repr__(self) -> str:
        target = f"item={self.caso_item_id}" if self.caso_item_id else "caso"
        return f"<RmaCasoHistorial(id={self.id}, caso_id={self.caso_id}, {target}, campo='{self.campo}')>"
