"""
PedidoCompraLineaFacturadaCt — invoiced units per item of a Compras operation, per invoice.

The per-invoice split of `pedido_compra_lineas_facturadas` (sell in varias facturas S3/S4): one bucket per linked
supplier invoice (`ct_transaction_id`) holding that invoice's net (minus the credit notes imputed to that very
invoice), dropped when below one unit like the aggregate; and one bucket with `ct_transaction_id` NULL holding the
signed net of the credit notes imputed to the whole operation. Per (pedido, item) the buckets add up to the aggregate
before its clamp. Written only by `erp_matching_service.reconciliar_lineas_facturadas`, next to the aggregate, and
copied by `copiar_lineas_facturadas`; read only by a line that picks specific invoices
(`app.services.sell_in.facturas_elegidas`). The aggregate and all its readers are untouched. Migration
`20261114_sell_in_facturas_elegidas`.
"""

from sqlalchemy import BigInteger, CheckConstraint, Column, ForeignKey, Index, Integer, Numeric, String, text

from app.core.database import Base


class PedidoCompraLineaFacturadaCt(Base):
    __tablename__ = "pedido_compra_lineas_facturadas_ct"
    __table_args__ = (
        CheckConstraint("cantidad <> 0", name="ck_pedido_compra_lineas_facturadas_ct_cantidad"),
        CheckConstraint("moneda IN ('ARS', 'USD')", name="ck_pedido_compra_lineas_facturadas_ct_moneda"),
        Index("ix_pedido_compra_lineas_facturadas_ct_pedido_id", "pedido_id"),
        # NULLS NOT DISTINCT needs PostgreSQL 15: two partial unique indexes instead, one per kind of bucket.
        Index(
            "uq_pedido_compra_lineas_facturadas_ct_factura",
            "pedido_id",
            "ct_transaction_id",
            "item_id",
            unique=True,
            postgresql_where=text("ct_transaction_id IS NOT NULL"),
        ),
        Index(
            "uq_pedido_compra_lineas_facturadas_ct_pedido",
            "pedido_id",
            "item_id",
            unique=True,
            postgresql_where=text("ct_transaction_id IS NULL"),
        ),
    )

    id = Column(BigInteger, primary_key=True)
    pedido_id = Column(BigInteger, ForeignKey("pedidos_compra.id", ondelete="CASCADE"), nullable=False)
    # The invoice; NULL: the credit notes imputed to the whole operation (no invoice of their own).
    ct_transaction_id = Column(BigInteger, nullable=True)
    item_id = Column(Integer, nullable=False)
    cantidad = Column(Integer, nullable=False)  # signed on the NULL bucket, >= 1 on an invoice's
    importe_neto = Column(Numeric(18, 2), nullable=True)
    moneda = Column(String(3), nullable=True)
