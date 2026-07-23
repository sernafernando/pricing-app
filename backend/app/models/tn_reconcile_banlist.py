from sqlalchemy import Column, Integer, ForeignKey, DateTime, Text, String
from sqlalchemy.orm import relationship
from sqlalchemy.sql import func
from app.core.database import Base


class TnReconcileBanlist(Base):
    """EAN-keyed ban list for the TN reconciliation view.

    Mirrors `ItemSinMLABanlist`. A banned EAN is hidden from the actionable
    reconciliation view until explicitly unbanned; entries persist across
    GBP report refreshes (verdicts are recomputed live, bans are not).
    """

    __tablename__ = "tn_reconcile_banlist"

    id = Column(Integer, primary_key=True, index=True)
    ean = Column(String(100), unique=True, index=True, nullable=False)
    motivo = Column(Text, nullable=True)

    usuario_id = Column(Integer, ForeignKey("usuarios.id"), nullable=False)
    fecha_creacion = Column(DateTime(timezone=True), server_default=func.now())

    usuario = relationship("Usuario", backref="tn_reconcile_baneados")

    def __repr__(self):
        return f"<TnReconcileBanlist(ean={self.ean})>"
