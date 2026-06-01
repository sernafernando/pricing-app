"""SQLAlchemy model for stock_por_deposito.

Stores the available stock per item/depot as returned by the ERP endpoint
``ItemStorage_funGetXMLData``. This is the same data source used by erp_sync
for ``productos_erp.stock`` (intStor_id=1), extended to all depots.

Synced by: ``app.scripts.sync_stock_por_deposito``
Used by: ``app.routers.consultas`` (ranking, resumen, kpis LATERAL JOINs)
"""

from datetime import datetime, UTC

from sqlalchemy import Column, DateTime, Index, Integer, PrimaryKeyConstraint

from app.core.database import Base


class StockPorDeposito(Base):
    __tablename__ = "stock_por_deposito"

    item_id: int = Column(Integer, nullable=False)
    stor_id: int = Column(Integer, nullable=False)
    stock: int = Column(Integer, nullable=False, default=0, server_default="0")
    updated_at: datetime = Column(
        DateTime(timezone=True),
        nullable=False,
        default=lambda: datetime.now(UTC),
        server_default="NOW()",
    )

    __table_args__ = (
        PrimaryKeyConstraint("item_id", "stor_id", name="pk_stock_por_deposito"),
        Index("ix_stock_por_deposito_stor_item", "stor_id", "item_id"),
    )
