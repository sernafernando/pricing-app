"""Per-MLA revision queue state for PARA GANAR Advisor (P4)."""

from __future__ import annotations

from sqlalchemy import Column, DateTime, ForeignKey, Integer, String, func
from sqlalchemy.orm import relationship

from app.core.database import Base

REVISION_PENDIENTE = "pendiente"
REVISION_SIN_NOVEDADES = "sin_novedades"
REVISION_ESTADOS = (REVISION_PENDIENTE, REVISION_SIN_NOVEDADES)


class ParaGanarRevisionMla(Base):
    """Outcome of periodic/manual evaluation for the Advisor work queue."""

    __tablename__ = "para_ganar_revision_mla"

    mla = Column(String(32), primary_key=True)
    estado = Column(String(32), nullable=False, index=True)
    evaluated_at = Column(
        DateTime(timezone=True),
        server_default=func.now(),
        nullable=False,
    )
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
