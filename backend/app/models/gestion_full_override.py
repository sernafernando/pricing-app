"""PM override for Gestión Full replenishment qty, keyed by inventory_id."""

from __future__ import annotations

from sqlalchemy import Column, DateTime, ForeignKey, Integer, Text, func
from sqlalchemy.orm import relationship

from app.core.database import Base


class GestionFullOverride(Base):
    __tablename__ = "gestion_full_override"

    inventory_id = Column(Text, primary_key=True)
    cantidad = Column(Integer, nullable=False)
    updated_by_id = Column(
        Integer,
        ForeignKey("usuarios.id", ondelete="SET NULL"),
        nullable=True,
        index=True,
    )
    updated_at = Column(
        DateTime(timezone=True),
        server_default=func.now(),
        onupdate=func.now(),
        nullable=False,
    )

    updated_by = relationship("Usuario", foreign_keys=[updated_by_id])
