from sqlalchemy import Column, Integer, String, DateTime, Text, ForeignKey
from sqlalchemy.sql import func
from app.core.database import Base


class EnvioTurboBanlist(Base):
    """
    Modelo para banlist de envíos Turbo problemáticos.
    
    Permite excluir manualmente envíos con:
    - Estados buggeados (stuck en not_delivered por meses)
    - Inconsistencias con ML Webhook
    - Duplicados o errores de sincronización
    """
    __tablename__ = "envios_turbo_banlist"

    id = Column(Integer, primary_key=True, index=True)
    mlshippingid = Column(String(50), nullable=False, unique=True, index=True)
    motivo = Column(String(500), nullable=True)
    baneado_por = Column(Integer, ForeignKey('usuarios.id'), nullable=True)
    baneado_at = Column(DateTime(timezone=True), server_default=func.now())
    notas = Column(Text, nullable=True)

    def __repr__(self):
        return f"<EnvioTurboBanlist(mlshippingid='{self.mlshippingid}', motivo='{self.motivo}')>"
