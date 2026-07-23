from sqlalchemy import Column, Integer, ForeignKey, DateTime, Text, String
from sqlalchemy.orm import relationship
from sqlalchemy.sql import func
from app.core.database import Base


class TnReconcileBanlist(Base):
    """EAN-keyed ban list for the TN reconciliation view.

    Mirrors `ItemSinMLABanlist`. Banning an EAN means "we don't want to
    publish this" — it hides ONLY the publish-candidate verdicts
    (FALTA_VINCULAR, FALTA_PUBLICAR) until explicitly unbanned. It NEVER
    hides a data-quality anomaly (MAL_VINCULADO, MAL_PUBLICADO, DUPLICADO):
    banning is not a way to sweep an existing mis-publication out of review.
    Entries persist across GBP report refreshes (verdicts are recomputed
    live, bans are not) — see `tn_reconciliation_service.compute_verdicts`.
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
