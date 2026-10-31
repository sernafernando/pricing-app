"""PM ready/lock for Gestión Full, keyed by ERP product + MLAU."""

from __future__ import annotations

from sqlalchemy import Column, DateTime, ForeignKey, Integer, Text, func
from sqlalchemy.orm import relationship

from app.core.database import Base


class GestionFullPmReady(Base):
    """Presence of a row means the PM closed this line (qty_pm frozen, override locked)."""

    __tablename__ = "gestion_full_pm_ready"

    producto_item_id = Column(
        Integer,
        ForeignKey("productos_erp.item_id", ondelete="CASCADE"),
        primary_key=True,
    )
    user_product_id = Column(Text, primary_key=True)
    inventory_id = Column(Text, nullable=False)
    qty_pm = Column(Integer, nullable=False)
    ready_by_id = Column(
        Integer,
        ForeignKey("usuarios.id", ondelete="SET NULL"),
        nullable=True,
        index=True,
    )
    ready_at = Column(
        DateTime(timezone=True),
        server_default=func.now(),
        nullable=False,
    )

    ready_by = relationship("Usuario", foreign_keys=[ready_by_id])
