"""
PedidoCompraLineaFacturada — invoiced units per item of a Compras operation.

App-side snapshot of the ERP lines of the supplier invoice linked to a
`pedidos_compra` row (`ct_transaction_id`), so the brand sell in reads units
from app tables only. Written exclusively by
`erp_matching_service.reconciliar_lineas_facturadas` (link/unlink and every
ERP sync); never edited by hand.

`item_id` has no FK to `productos_erp`: the ERP mirror may hold an item the
catalog sync has not brought yet, and the snapshot must not fail on it.
"""

from sqlalchemy import BigInteger, CheckConstraint, Column, ForeignKey, Integer, UniqueConstraint

from app.core.database import Base


class PedidoCompraLineaFacturada(Base):
    __tablename__ = "pedido_compra_lineas_facturadas"
    __table_args__ = (
        UniqueConstraint("pedido_id", "item_id", name="uq_pedido_compra_lineas_facturadas_pedido_item"),
        CheckConstraint("cantidad > 0", name="ck_pedido_compra_lineas_facturadas_cantidad_positiva"),
    )

    id = Column(BigInteger, primary_key=True)
    pedido_id = Column(BigInteger, ForeignKey("pedidos_compra.id", ondelete="CASCADE"), nullable=False)
    item_id = Column(Integer, nullable=False, index=True)
    # Whole units, like sell_in_compra_items.cantidad (ERP purchase lines carry
    # integer it_qty; verified on prod 2026-10-19).
    cantidad = Column(Integer, nullable=False)
