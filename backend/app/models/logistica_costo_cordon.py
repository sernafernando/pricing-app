"""
Costos de envío por logística × cordón con historial.

Cada registro define el costo de un cordón para una logística específica
con fecha de vigencia. El query siempre agarra el más reciente por
(logistica_id, cordon) con vigente_desde <= hoy.
"""

from sqlalchemy import Column, Integer, String, Date, DateTime, Numeric, ForeignKey, Index
from sqlalchemy.sql import func
from sqlalchemy.orm import relationship
from app.core.database import Base


class LogisticaCostoCordon(Base):
    """Costo de envío por logística y cordón, con historial."""

    __tablename__ = "logistica_costo_cordon"

    id = Column(Integer, primary_key=True, index=True)
    logistica_id = Column(Integer, ForeignKey("logisticas.id"), nullable=False)
    cordon = Column(String(20), nullable=False)  # 'CABA', 'Cordon 1', 'Cordon 2', 'Cordon 3'
    costo = Column(Numeric(12, 2), nullable=False)
    costo_turbo = Column(Numeric(12, 2), nullable=True)  # Costo diferenciado para envíos turbo
    vigente_desde = Column(Date, nullable=False)
    created_at = Column(DateTime(timezone=True), server_default=func.now())

    # Relationships
    logistica = relationship("Logistica", lazy="joined")

    __table_args__ = (
        Index("idx_costo_logistica_cordon", "logistica_id", "cordon"),
        Index("idx_costo_vigente", "vigente_desde"),
    )

    def __repr__(self) -> str:
        return f"<LogisticaCostoCordon(logistica={self.logistica_id}, cordon={self.cordon}, ${self.costo})>"
