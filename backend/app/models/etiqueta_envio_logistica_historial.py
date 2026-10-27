"""
History of logistics changes of shipping labels.

Every change of etiquetas_envio.logistica_id leaves one row here: old value,
new value, who (usuario and/or operador), when and source (asignar / masivo /
pistoleado / manual). A Postgres trigger writes it
(app/services/etiquetas/logistica_historial_sql.py), so no write path can skip
it. It outlives the label (no FK to etiquetas_envio).
"""

from sqlalchemy import Column, DateTime, ForeignKey, Index, Integer, String, Text
from sqlalchemy.sql import func
from app.core.database import Base


class EtiquetaEnvioLogisticaHistorial(Base):
    """One logistics change of a label (inserted by the trigger, not by the app)."""

    __tablename__ = "etiquetas_envio_logistica_historial"

    id = Column(Integer, primary_key=True)
    shipping_id = Column(String(50), nullable=False)
    logistica_anterior_id = Column(Integer, ForeignKey("logisticas.id"), nullable=True)
    logistica_nueva_id = Column(Integer, ForeignKey("logisticas.id"), nullable=True)
    # No FK: a bad id in the transaction setting must never make the label write fail.
    usuario_id = Column(Integer, nullable=True)
    operador_id = Column(Integer, nullable=True)
    origen = Column(Text, nullable=True)  # asignar / masivo / pistoleado / manual / deshacer
    cambiado_en = Column(DateTime(timezone=True), server_default=func.now(), nullable=False)

    __table_args__ = (Index("idx_etiq_logistica_historial_shipping", "shipping_id", "cambiado_en"),)

    def __repr__(self) -> str:
        return (
            f"<EtiquetaEnvioLogisticaHistorial(shipping_id={self.shipping_id}, "
            f"{self.logistica_anterior_id}->{self.logistica_nueva_id})>"
        )
