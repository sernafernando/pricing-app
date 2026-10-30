"""Snapshot of the latest Full inbound reception per inventory_id (Gestión Full Target)."""

from __future__ import annotations

from sqlalchemy import BigInteger, Column, DateTime, Integer, Text, func

from app.core.database import Base


class MlFulfillmentLastInbound(Base):
    __tablename__ = "ml_fulfillment_last_inbound"

    inventory_id = Column(Text, primary_key=True)
    # Null when ML was checked and no INBOUND_RECEPTION fell in the lookback window.
    cantidad = Column(Integer, nullable=True)
    occurred_at = Column(DateTime(timezone=True), nullable=True)
    operation_id = Column(BigInteger, nullable=True)
    inbound_id = Column(Text, nullable=True)
    fetched_at = Column(
        DateTime(timezone=True),
        server_default=func.now(),
        nullable=False,
    )
