"""ML sale costs re-frozen at costo SI (sell-in-costo-si T3 PR 7, migration 20261127_ml_costo_si).

- `ml_costo_si_dirty`: the products whose ML sales must be re-frozen and from which sale date. A costo SI recompute
  queues them (`services/costo_si/despues/ml_ventas.py`, the product and every combo containing it); `sell.drain`
  drains it after the costo SI queue (`services/ml_orders_ingestion/recongelar_costo_si.py`), no cron.
- `ml_order_item_costos_backups`: every `ml_order_item_costos` row a re-freeze changed, as it was before (L15).
"""

from sqlalchemy import BigInteger, Column, Date, DateTime, Index, Integer, String, Text, text
from sqlalchemy.dialects.postgresql import JSONB
from sqlalchemy.sql import func

from app.core.database import Base


class MlCostoSiDirty(Base):
    __tablename__ = "ml_costo_si_dirty"

    producto_item_id = Column(Integer, primary_key=True, autoincrement=False)
    desde = Column(Date, nullable=True)  # first sale date to re-freeze; NULL: every sale of the product
    enqueued_at = Column(DateTime(timezone=True), nullable=False, server_default=func.now())
    attempts = Column(Integer, nullable=False, server_default=text("0"))
    last_error = Column(Text, nullable=True)


class MlOrderItemCostoBackup(Base):
    __tablename__ = "ml_order_item_costos_backups"
    __table_args__ = (Index("ix_ml_order_item_costos_backups_costo", "costo_id", "created_at"),)

    id = Column(BigInteger, primary_key=True)
    costo_id = Column(Integer, nullable=False)  # ml_order_item_costos.id
    order_id = Column(BigInteger, nullable=False)
    item_id = Column(String(20), nullable=False)
    variation_id = Column(BigInteger, nullable=True)
    fila = Column(JSONB, nullable=False)  # the whole row before the re-freeze
    motivo = Column(Text, nullable=False)
    desde = Column(Date, nullable=True)
    created_at = Column(DateTime(timezone=True), nullable=False, server_default=func.now())
