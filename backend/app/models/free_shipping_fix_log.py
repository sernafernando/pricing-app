"""
Log de intentos de auto-fix de free_shipping en MercadoLibre.

Registra cada intento de desactivar envío gratis en items que tienen
free_shipping_error=true para evitar disparar PUTs repetidos.
"""

from sqlalchemy import Column, Integer, String, DateTime, Boolean, Text, Index
from sqlalchemy.sql import func
from app.core.database import Base


class FreeShippingFixLog(Base):
    """Registro de cada intento de PUT free_shipping=false a ML."""

    __tablename__ = "free_shipping_fix_log"

    id = Column(Integer, primary_key=True, index=True)
    mla_id = Column(String(30), nullable=False, index=True)

    # Resultado del intento
    success = Column(Boolean, nullable=False)
    skipped = Column(Boolean, default=False, nullable=False)
    skip_reason = Column(String(100), nullable=True)

    # Contexto del item al momento del fix
    item_price = Column(String(30), nullable=True)
    mandatory_free_shipping = Column(Boolean, default=False, nullable=False)

    # Respuesta de ML (para debug)
    ml_response_status = Column(Integer, nullable=True)
    ml_response_body = Column(Text, nullable=True)

    # Auditoría
    created_at = Column(DateTime(timezone=True), server_default=func.now(), nullable=False)

    __table_args__ = (Index("idx_fs_fix_log_mla_created", "mla_id", "created_at"),)

    def __repr__(self) -> str:
        status = "OK" if self.success else ("SKIP" if self.skipped else "FAIL")
        return f"<FreeShippingFixLog(mla_id={self.mla_id}, {status}, {self.created_at})>"
