from sqlalchemy import Column, DateTime, ForeignKey, Integer, String, Text, UniqueConstraint
from sqlalchemy.orm import relationship
from sqlalchemy.sql import func

from app.core.database import Base


class TnPublishOverride(Base):
    """Operator-edited field override for a TN publish draft, keyed by EAN.

    `(ean, campo)` unique — EAN is the GBP `Código`, 100% populated, already
    the join key for `get_product_by_sku`, the mirror `variant_sku`, and the
    reconcile banlist. See design's `tn_publish_override` decision.
    """

    __tablename__ = "tn_publish_override"
    __table_args__ = (UniqueConstraint("ean", "campo", name="uq_tn_publish_override_ean_campo"),)

    id = Column(Integer, primary_key=True, index=True)
    ean = Column(String(100), nullable=False, index=True)
    campo = Column(String(50), nullable=False)
    valor = Column(Text, nullable=False)

    usuario_id = Column(Integer, ForeignKey("usuarios.id", ondelete="CASCADE"), nullable=False)
    fecha_actualizacion = Column(DateTime(timezone=True), server_default=func.now())

    usuario = relationship("Usuario", backref="tn_publish_overrides")

    def __repr__(self):
        return f"<TnPublishOverride(ean={self.ean}, campo={self.campo})>"
