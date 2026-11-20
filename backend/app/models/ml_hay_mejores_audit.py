"""Append-only lean audit for hay_mejores flag transitions and Auto toggle.

Not MercadoLibre writes — those stay on ``ml_write_log``. Enroll enrich reuses
``ml_write_log.payload`` JSONB; this table covers flag-time snapshots and
Auto-aplicación on/off history (usuario_id nullable for system actors).
"""

from sqlalchemy import BigInteger, Column, DateTime, Index, Integer, Text, func
from sqlalchemy.dialects.postgresql import JSONB

from app.core.database import Base

KIND_FLAG_TRANSITION = "flag_transition"
KIND_AUTO_TOGGLE = "auto_toggle"


class MlHayMejoresAudit(Base):
    __tablename__ = "ml_hay_mejores_audit"
    __table_args__ = (Index("ix_ml_hay_mejores_audit_item_created", "item_id", "created_at"),)

    id = Column(BigInteger, primary_key=True, autoincrement=True)
    item_id = Column(Text, nullable=False)  # MLA
    kind = Column(Text, nullable=False)  # flag_transition | auto_toggle
    usuario_id = Column(Integer, nullable=True)  # usuarios.id; None = system/worker
    payload = Column(JSONB, nullable=False)
    created_at = Column(DateTime(timezone=True), nullable=False, server_default=func.now())
