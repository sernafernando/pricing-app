"""
PedidoCompraOc — N OC identity triples linked to one pedido (D-MULTI).

Relation table is the source of truth. Header `pedidos_compra.oc_*` stays
as a first-link cache; writers update both.
"""

from datetime import UTC, datetime
from typing import TYPE_CHECKING, Sequence

from sqlalchemy import BigInteger, Column, DateTime, ForeignKey, Index, Integer, UniqueConstraint
from sqlalchemy.orm import Session, relationship

from app.core.database import Base

if TYPE_CHECKING:
    from app.models.pedido_compra import PedidoCompra


class PedidoCompraOc(Base):
    """One complete ERP OC triple belonging to a pedido de compra."""

    __tablename__ = "pedido_compra_ocs"

    id = Column(BigInteger, primary_key=True, index=True)
    pedido_id = Column(
        BigInteger,
        ForeignKey("pedidos_compra.id", ondelete="CASCADE"),
        nullable=False,
    )
    oc_comp_id = Column(Integer, nullable=False)
    oc_bra_id = Column(Integer, nullable=False)
    oc_poh_id = Column(BigInteger, nullable=False)
    created_at = Column(
        DateTime(timezone=True),
        nullable=False,
        default=lambda: datetime.now(UTC),
    )

    pedido = relationship("PedidoCompra", foreign_keys=[pedido_id], back_populates="ocs")

    __table_args__ = (
        UniqueConstraint(
            "pedido_id",
            "oc_comp_id",
            "oc_bra_id",
            "oc_poh_id",
            name="uq_pedido_compra_ocs_triple",
        ),
        Index("ix_pedido_compra_ocs_pedido_id", "pedido_id"),
        Index("ix_pedido_compra_ocs_oc_poh_id", "oc_poh_id"),
    )

    def as_triple(self) -> tuple[int, int, int]:
        return (int(self.oc_comp_id), int(self.oc_bra_id), int(self.oc_poh_id))

    def __repr__(self) -> str:
        return (
            f"<PedidoCompraOc(id={self.id}, pedido_id={self.pedido_id}, "
            f"oc=({self.oc_comp_id},{self.oc_bra_id},{self.oc_poh_id}))>"
        )


def triples_for_pedido(session: Session, pedido: "PedidoCompra") -> list[tuple[int, int, int]]:
    """SoT triples from `pedido_compra_ocs`, else the header first-link cache."""
    rows: Sequence[PedidoCompraOc] = (
        session.query(PedidoCompraOc).filter(PedidoCompraOc.pedido_id == pedido.id).order_by(PedidoCompraOc.id).all()
    )
    if rows:
        return [row.as_triple() for row in rows]
    if getattr(pedido, "oc_poh_id", None) is not None:
        return [(int(pedido.oc_comp_id), int(pedido.oc_bra_id), int(pedido.oc_poh_id))]
    return []
