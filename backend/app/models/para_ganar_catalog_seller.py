"""Per-catalog seller roster + disposition for PARA GANAR TOP / ranking."""

from __future__ import annotations

from sqlalchemy import Column, DateTime, ForeignKey, Integer, String, UniqueConstraint, func
from sqlalchemy.orm import relationship

from app.core.database import Base

# active | ignore_participant | hide | exclude_from_top
DISPOSITION_ACTIVE = "active"
DISPOSITION_IGNORE_PARTICIPANT = "ignore_participant"
DISPOSITION_HIDE = "hide"
DISPOSITION_EXCLUDE_FROM_TOP = "exclude_from_top"
DISPOSITION_VALUES = (
    DISPOSITION_ACTIVE,
    DISPOSITION_IGNORE_PARTICIPANT,
    DISPOSITION_HIDE,
    DISPOSITION_EXCLUDE_FROM_TOP,
)


class ParaGanarCatalogSeller(Base):
    __tablename__ = "para_ganar_catalog_sellers"

    id = Column(Integer, primary_key=True, index=True)
    catalog_product_id = Column(String(50), nullable=False, index=True)
    seller_id = Column(String(32), nullable=False, index=True)
    nickname = Column(String(128), nullable=True)
    disposition = Column(String(32), nullable=False, server_default=DISPOSITION_ACTIVE)
    last_item_id = Column(String(32), nullable=True)
    last_seen_at = Column(DateTime(timezone=True), nullable=True)
    created_at = Column(DateTime(timezone=True), server_default=func.now(), nullable=False)
    updated_at = Column(DateTime(timezone=True), server_default=func.now(), onupdate=func.now(), nullable=False)
    updated_by_id = Column(Integer, ForeignKey("usuarios.id", ondelete="SET NULL"), nullable=True, index=True)

    updated_by = relationship("Usuario", foreign_keys=[updated_by_id])

    __table_args__ = (
        UniqueConstraint(
            "catalog_product_id",
            "seller_id",
            name="uq_para_ganar_catalog_seller",
        ),
    )
