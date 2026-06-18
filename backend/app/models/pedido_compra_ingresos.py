"""
PedidoCompraIngreso — registro append-only de recepción de mercadería.

Cada fila representa una tanda (batch) de recepción de una línea OC específica
(pod_id). La tabla es append-only: el servicio nunca emite UPDATE ni DELETE.

Modo SIN-OC: se permite una fila centinela con pod_id=NULL, oc_*=NULL,
cantidad_recibida=1 (placeholder > 0) para auditar quién/cuándo confirmó
la recepción cuando el pedido no tiene OC vinculada. El índice parcial
ix_pci_pod (WHERE pod_id IS NOT NULL) excluye estas filas del cálculo
de saldo, evitando contaminar la matemática CON-OC.
"""

from sqlalchemy import (
    BigInteger,
    CheckConstraint,
    Column,
    Date,
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


class PedidoCompraIngreso(Base):
    """Registro de recepción física de mercadería para un pedido de compra."""

    __tablename__ = "pedido_compra_ingresos"

    id = Column(BigInteger, primary_key=True, index=True)
    pedido_id = Column(
        BigInteger,
        ForeignKey("pedidos_compra.id", ondelete="RESTRICT"),
        nullable=False,
    )
    # Snapshot de identidad de la línea OC (FK lógica sin constraint físico)
    oc_comp_id = Column(Integer, nullable=True)
    oc_bra_id = Column(Integer, nullable=True)
    oc_poh_id = Column(BigInteger, nullable=True)
    # pod_id es NULL solo en el registro centinela de modo SIN-OC
    pod_id = Column(BigInteger, nullable=True)
    item_id = Column(Integer, nullable=True)
    stor_id = Column(Integer, nullable=True)

    cantidad_recibida = Column(Numeric(18, 6), nullable=False)
    fecha_ingreso = Column(Date, nullable=True)
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

    # Relationships (read-only)
    pedido = relationship("PedidoCompra", foreign_keys=[pedido_id], lazy="select")
    usuario = relationship("Usuario", foreign_keys=[usuario_id], lazy="select")

    __table_args__ = (
        CheckConstraint("cantidad_recibida > 0", name="ck_pci_cantidad_positiva"),
        Index("ix_pci_pedido", "pedido_id"),
        # ix_pci_pod is partial in PostgreSQL (WHERE pod_id IS NOT NULL).
        # In SQLite tests it's a plain index (partial index support varies by version).
        Index("ix_pci_pod", "pod_id"),
        Index("ix_pci_oc_linea", "oc_comp_id", "oc_bra_id", "oc_poh_id", "pod_id"),
    )

    def __repr__(self) -> str:
        return (
            f"<PedidoCompraIngreso(id={self.id}, pedido_id={self.pedido_id}, "
            f"pod_id={self.pod_id}, cantidad_recibida={self.cantidad_recibida})>"
        )
