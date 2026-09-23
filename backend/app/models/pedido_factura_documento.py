"""
PedidoFacturaDocumento — normalized supplier invoice row on a pedido.

Constancia: a row stores an identified factura number. It is not “cargada”.
Cargada: Administración ERP check (`cargada=true`). ERP `ct_transaction`
is never identity. Raw `pedidos_compra.facturas_documento` is kept;
`pedidos_documento` is write-once and must not be used as factura identity.
"""

from sqlalchemy import (
    BigInteger,
    Boolean,
    Column,
    DateTime,
    ForeignKey,
    Index,
    Integer,
    String,
    UniqueConstraint,
    text,
)
from sqlalchemy.orm import relationship
from sqlalchemy.sql import func

from app.core.database import Base


class PedidoFacturaDocumento(Base):
    """One identified invoice document number belonging to a pedido de compra."""

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
    cargada = Column(Boolean, nullable=False, default=False, server_default="false")
    cargada_marked_at = Column(DateTime(timezone=True), nullable=True)
    cargada_marked_by_id = Column(
        Integer,
        ForeignKey("usuarios.id", ondelete="SET NULL"),
        nullable=True,
    )
    alerta_pendiente_hasta = Column(DateTime(timezone=True), nullable=True)
    alerta_disparada_at = Column(DateTime(timezone=True), nullable=True)

    pedido = relationship("PedidoCompra", foreign_keys=[pedido_id], back_populates="factura_documentos")
    created_by = relationship("Usuario", foreign_keys=[created_by_id], lazy="select")
    cargada_marked_by = relationship("Usuario", foreign_keys=[cargada_marked_by_id], lazy="select")

    __table_args__ = (
        Index("ix_pedido_factura_documentos_pedido_id", "pedido_id"),
        UniqueConstraint("pedido_id", "numero", name="uq_pedido_factura_documentos_pedido_id_numero"),
        Index(
            "ix_pedido_factura_documentos_alerta_pendiente",
            "alerta_pendiente_hasta",
            postgresql_where=text(
                "cargada = true AND alerta_disparada_at IS NULL AND alerta_pendiente_hasta IS NOT NULL"
            ),
        ),
    )

    def __repr__(self) -> str:
        return (
            f"<PedidoFacturaDocumento(id={self.id}, pedido_id={self.pedido_id}, "
            f"numero='{self.numero}', cargada={self.cargada})>"
        )
