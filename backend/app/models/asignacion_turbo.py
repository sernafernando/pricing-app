from sqlalchemy import Column, Integer, String, Numeric, DateTime, ForeignKey, Text
from sqlalchemy.sql import func
from sqlalchemy.orm import relationship
from app.core.database import Base


class AsignacionTurbo(Base):
    """
    Modelo para asignaciones de envíos Turbo a motoqueros.
    Cada registro representa un envío asignado a un motoquero específico.
    """

    __tablename__ = "asignaciones_turbo"

    id = Column(Integer, primary_key=True, index=True)
    mlshippingid = Column(String(50), nullable=False, index=True)  # FK a tb_mercadolibre_orders_shipping
    motoquero_id = Column(Integer, ForeignKey("motoqueros.id", ondelete="CASCADE"), nullable=False, index=True)
    zona_id = Column(Integer, ForeignKey("zonas_reparto.id", ondelete="SET NULL"), nullable=True, index=True)

    # Datos de dirección
    direccion = Column(String(500), nullable=False)
    latitud = Column(Numeric(10, 8), nullable=True)
    longitud = Column(Numeric(11, 8), nullable=True)

    # Routing
    orden_ruta = Column(Integer, nullable=True)  # Orden de entrega optimizado (1, 2, 3...)

    # Estado del envío
    estado = Column(String(20), default="pendiente", nullable=False, index=True)
    # Estados posibles: 'pendiente', 'en_camino', 'entregado', 'cancelado'

    asignado_por = Column(String(20), nullable=True)  # 'automatico' o 'manual'
    asignado_at = Column(DateTime(timezone=True), server_default=func.now())
    entregado_at = Column(DateTime(timezone=True), nullable=True)

    notas = Column(Text, nullable=True)

    # Relationships
    motoquero = relationship("Motoquero", back_populates="asignaciones")
    zona = relationship("ZonaReparto", back_populates="asignaciones")

    def __repr__(self):
        return f"<AsignacionTurbo(id={self.id}, mlshippingid='{self.mlshippingid}', motoquero_id={self.motoquero_id}, estado='{self.estado}')>"
