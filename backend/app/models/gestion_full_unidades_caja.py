"""Units per closed box for Gestión Full, keyed by ERP product."""

from __future__ import annotations

from sqlalchemy import Column, DateTime, ForeignKey, Integer, func
from sqlalchemy.orm import relationship

from app.core.database import Base


class GestionFullUnidadesCaja(Base):
    __tablename__ = "gestion_full_unidades_caja"

    producto_item_id = Column(
        Integer,
        ForeignKey("productos_erp.item_id", ondelete="CASCADE"),
        primary_key=True,
    )
    unidades = Column(Integer, nullable=False)
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
