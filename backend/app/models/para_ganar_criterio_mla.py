"""Per-MLA criteria for the PARA GANAR advisor (unit of work = MLA)."""

from __future__ import annotations

from sqlalchemy import Boolean, Column, DateTime, ForeignKey, Integer, Numeric, String, func
from sqlalchemy.orm import relationship

from app.core.database import Base


class ParaGanarCriterioMla(Base):
    __tablename__ = "para_ganar_criterios_mla"

    mla = Column(String(32), primary_key=True)
    markup_min = Column(Numeric(8, 2), nullable=True)
    markup_max = Column(Numeric(8, 2), nullable=True)
    top_sellers = Column(Integer, nullable=True)
    precio_min = Column(Numeric(14, 2), nullable=True)
    precio_max = Column(Numeric(14, 2), nullable=True)
    ganar_catalogo = Column(Boolean, nullable=False, server_default="true")
    ignorar_internacionales = Column(Boolean, nullable=False, server_default="false")
    descartar_stock_residual = Column(Boolean, nullable=False, server_default="false")
    descartar_reputacion_baja = Column(Boolean, nullable=False, server_default="false")
    techo_monopolio = Column(Boolean, nullable=False, server_default="false")
    created_at = Column(DateTime(timezone=True), server_default=func.now(), nullable=False)
    updated_at = Column(DateTime(timezone=True), server_default=func.now(), onupdate=func.now(), nullable=False)
    updated_by_id = Column(Integer, ForeignKey("usuarios.id", ondelete="SET NULL"), nullable=True, index=True)

    updated_by = relationship("Usuario", foreign_keys=[updated_by_id])
