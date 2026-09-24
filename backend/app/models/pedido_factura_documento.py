"""
PedidoFacturaDocumento — normalized supplier invoice row on a pedido.

Option A (D-FACT): “factura cargada” means this table has ≥1 row for the
pedido. ERP `ct_transaction` multi-link is deprecated and is never identity.
Raw `pedidos_compra.facturas_documento` is kept; `pedidos_documento` is
write-once and must not be used as factura identity.
"""

from sqlalchemy import BigInteger, Column, DateTime, ForeignKey, Index, Integer, String, UniqueConstraint
from sqlalchemy.orm import relationship
from sqlalchemy.sql import func

from app.core.database import Base


class PedidoFacturaDocumento(Base):
    """One loaded invoice document number belonging to a pedido de compra."""

    __tablename__ = "pedido_factura_documentos"

    id = Column(BigInteger, primary_key=True, index=True)
    pedido_id = Column(
        BigInteger,
        ForeignKey("pedidos_compra.id", ondelete="CASCADE"),
        nullable=False,
    )
    numero = Column(String(100), nullable=False)
    created_at = Column(
        DateTime(timezone=True),
        nullable=False,
        server_default=func.now(),
    )
    created_by_id = Column(
        Integer,
        ForeignKey("usuarios.id", ondelete="RESTRICT"),
        nullable=False,
    )

    pedido = relationship("PedidoCompra", foreign_keys=[pedido_id], back_populates="factura_documentos")
    created_by = relationship("Usuario", foreign_keys=[created_by_id], lazy="select")

    __table_args__ = (
        Index("ix_pedido_factura_documentos_pedido_id", "pedido_id"),
        UniqueConstraint("pedido_id", "numero", name="uq_pedido_factura_documentos_pedido_id_numero"),
    )

    def __repr__(self) -> str:
        return f"<PedidoFacturaDocumento(id={self.id}, pedido_id={self.pedido_id}, numero='{self.numero}')>"
