"""Periodicidad subscriptions for PARA GANAR — primary key is EAN."""

from __future__ import annotations

from sqlalchemy import (
    Boolean,
    Column,
    DateTime,
    ForeignKey,
    Integer,
    String,
    func,
)
from sqlalchemy.dialects.postgresql import JSONB
from sqlalchemy.orm import relationship

from app.core.database import Base

SCOPE_ALL = "all"
SCOPE_MLAS = "mlas"
SCOPE_RULES = "rules"
SCOPE_MODES = (SCOPE_ALL, SCOPE_MLAS, SCOPE_RULES)


class ParaGanarPeriodicidadEan(Base):
    """EAN subscribed to periodic catalog review."""

    __tablename__ = "para_ganar_periodicidad_ean"

    ean = Column(String(64), primary_key=True)
    enabled = Column(Boolean, nullable=False, server_default="true")
    scope_mode = Column(String(16), nullable=False, server_default=SCOPE_ALL)
    # Used when scope_mode=rules (OR within each dimension; AND across non-empty dims).
    tipos_publicacion = Column(JSONB, nullable=False, server_default="[]")
    pricelist_ids = Column(JSONB, nullable=False, server_default="[]")
    tienda_oficial_ids = Column(JSONB, nullable=False, server_default="[]")
    created_at = Column(DateTime(timezone=True), server_default=func.now(), nullable=False)
    updated_at = Column(
        DateTime(timezone=True),
        server_default=func.now(),
        onupdate=func.now(),
        nullable=False,
    )
    updated_by_id = Column(
        Integer,
        ForeignKey("usuarios.id", ondelete="SET NULL"),
        nullable=True,
        index=True,
    )

    updated_by = relationship("Usuario", foreign_keys=[updated_by_id])
    mlas = relationship(
        "ParaGanarPeriodicidadEanMla",
        back_populates="subscription",
        cascade="all, delete-orphan",
        lazy="selectin",
    )


class ParaGanarPeriodicidadEanMla(Base):
    """Explicit MLA inclusion when scope_mode=mlas."""

    __tablename__ = "para_ganar_periodicidad_ean_mla"

    ean = Column(
        String(64),
        ForeignKey("para_ganar_periodicidad_ean.ean", ondelete="CASCADE"),
        primary_key=True,
    )
    mla = Column(String(32), primary_key=True)

    subscription = relationship("ParaGanarPeriodicidadEan", back_populates="mlas")
