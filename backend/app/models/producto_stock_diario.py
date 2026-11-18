"""SQLAlchemy model for `producto_stock_diario`: the daily stock photo (migration 20261122_producto_stock_diario).

Written by `app.services.ml_publications.view.stock_snapshot` (the `stock.snapshot` worker job), read by the
Auditoría de stock's Rotación. One row per product per day, only for products with some stock.
"""

from sqlalchemy import Column, Date, Index, Integer, PrimaryKeyConstraint

from app.core.database import Base


class ProductoStockDiario(Base):
    __tablename__ = "producto_stock_diario"

    fecha = Column(Date, nullable=False)
    item_id = Column(Integer, nullable=False)
    stock_erp = Column(Integer, nullable=False, default=0, server_default="0")
    stock_full = Column(Integer, nullable=False, default=0, server_default="0")

    __table_args__ = (
        PrimaryKeyConstraint("fecha", "item_id", name="pk_producto_stock_diario"),
        Index("ix_producto_stock_diario_item_fecha", "item_id", "fecha"),
    )
