"""
PedidoCompraArriboProgreso — arribo/retiro progress batches (pre-control).

Separate from `pedido_compra_ingresos` (control tandas). Saving progress never
closes the pedido: it stays in ESTADOS_ARRIBO (por recibir) until the operator
confirms arrival, which requires every OC line covered once progress exists.
Rows are only added while arriving; `deshacer_recibido` deletes them.
"""

from sqlalchemy import (
    BigInteger,
    CheckConstraint,
    Column,
    DateTime,
    ForeignKey,
    Index,
    Integer,
    Numeric,
    Text,
)
from sqlalchemy.orm import relationship
from sqlalchemy.sql import func

from app.core.database import Base


class PedidoCompraArriboProgreso(Base):
    """One batch line of physical arribo/retiro before depósito control."""

    __tablename__ = "pedido_compra_arribo_progreso"

    id = Column(BigInteger, primary_key=True)
    pedido_id = Column(
        BigInteger,
        ForeignKey("pedidos_compra.id", ondelete="RESTRICT"),
        nullable=False,
    )
    oc_comp_id = Column(Integer, nullable=True)
    oc_bra_id = Column(Integer, nullable=True)
    oc_poh_id = Column(BigInteger, nullable=True)
    pod_id = Column(BigInteger, nullable=False)
    item_id = Column(Integer, nullable=True)
    cantidad = Column(Numeric(18, 6), nullable=False)
    usuario_id = Column(
        Integer,
        ForeignKey("usuarios.id", ondelete="RESTRICT"),
        nullable=False,
    )
    observaciones = Column(Text, nullable=True)
    created_at = Column(
        DateTime(timezone=True),
        nullable=False,
        server_default=func.now(),
    )

    pedido = relationship("PedidoCompra", foreign_keys=[pedido_id], lazy="select")
    usuario = relationship("Usuario", foreign_keys=[usuario_id], lazy="select")

    __table_args__ = (
        CheckConstraint("cantidad > 0", name="ck_pcap_cantidad_positiva"),
        Index("ix_pcap_pedido", "pedido_id"),
        Index("ix_pcap_pedido_pod", "pedido_id", "pod_id"),
    )

    def __repr__(self) -> str:
        return (
            f"<PedidoCompraArriboProgreso(id={self.id}, pedido_id={self.pedido_id}, "
            f"pod_id={self.pod_id}, cantidad={self.cantidad})>"
        )
