"""
Control de bajada a depósito para items RMA.

Cada fila representa un item que fue marcado como "enviado físicamente"
en un caso RMA y necesita ser verificado por RMA y luego por depósito
mediante escaneo de serie o EAN.

Estado machine: pendiente → rma → deposito | pendiente/rma → no_baja
"""

from sqlalchemy import (
    BigInteger,
    CheckConstraint,
    Column,
    DateTime,
    ForeignKey,
    Integer,
    String,
    Text,
)
from sqlalchemy.orm import relationship
from sqlalchemy.sql import func

from app.core.database import Base


class ControlDepoItem(Base):
    """Entrada de control de bajada a depósito para un item RMA."""

    __tablename__ = "rma_control_deposito_items"

    id = Column(Integer, primary_key=True, index=True)

    # FK to source RMA item (unique — one checklist entry per RMA item)
    rma_caso_item_id = Column(
        Integer,
        ForeignKey("rma_caso_items.id", ondelete="CASCADE"),
        nullable=False,
        unique=True,
        index=True,
    )

    # Denormalized for fast scan lookup (avoid JOINs on hot path)
    caso_id = Column(Integer, ForeignKey("rma_casos.id", ondelete="CASCADE"), nullable=False, index=True)
    numero_caso = Column(String(20), nullable=False)
    serial_number = Column(String(100), nullable=True)
    ean = Column(String(50), nullable=True)
    item_id = Column(BigInteger, nullable=True)
    producto_desc = Column(String(500), nullable=True)

    # State machine: pendiente → rma → deposito | pendiente/rma → no_baja
    estado = Column(String(20), nullable=False, server_default="pendiente")

    # RMA team scan
    pistoleado_rma_por = Column(Integer, ForeignKey("usuarios.id"), nullable=True)
    pistoleado_rma_fecha = Column(DateTime(timezone=True), nullable=True)

    # Depósito team scan (requires operador PIN)
    pistoleado_depo_por = Column(Integer, ForeignKey("usuarios.id"), nullable=True)
    pistoleado_depo_operador_id = Column(Integer, ForeignKey("operadores.id"), nullable=True)
    pistoleado_depo_fecha = Column(DateTime(timezone=True), nullable=True)

    # No baja exception
    no_baja_confirmado_por = Column(Integer, ForeignKey("usuarios.id"), nullable=True)
    no_baja_fecha = Column(DateTime(timezone=True), nullable=True)
    no_baja_motivo = Column(Text, nullable=True)

    # System
    created_at = Column(DateTime(timezone=True), server_default=func.now(), nullable=False)
    updated_at = Column(DateTime(timezone=True), onupdate=func.now(), nullable=True)

    # Constraints
    __table_args__ = (
        CheckConstraint(
            "estado IN ('pendiente', 'rma', 'deposito', 'no_baja')",
            name="ck_control_depo_estado",
        ),
    )

    # Relationships
    rma_caso_item = relationship("RmaCasoItem", foreign_keys=[rma_caso_item_id])
    caso = relationship("RmaCaso", foreign_keys=[caso_id])
    pistoleado_rma_usuario = relationship("Usuario", foreign_keys=[pistoleado_rma_por])
    pistoleado_depo_usuario = relationship("Usuario", foreign_keys=[pistoleado_depo_por])
    pistoleado_depo_operador = relationship("Operador", foreign_keys=[pistoleado_depo_operador_id])
    no_baja_usuario = relationship("Usuario", foreign_keys=[no_baja_confirmado_por])

    def __repr__(self) -> str:
        return (
            f"<ControlDepoItem(id={self.id}, caso={self.numero_caso}, "
            f"serial='{self.serial_number}', estado='{self.estado}')>"
        )
