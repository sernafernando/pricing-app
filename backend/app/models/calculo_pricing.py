from sqlalchemy import Column, Integer, String, Numeric, DateTime, ForeignKey
from sqlalchemy.orm import relationship
from sqlalchemy.dialects.postgresql import JSONB
from datetime import datetime
from app.core.database import Base


class CalculoPricing(Base):
    __tablename__ = "calculos_pricing"

    id = Column(Integer, primary_key=True, index=True)
    usuario_id = Column(Integer, ForeignKey("usuarios.id"), nullable=False)
    descripcion = Column(String(500), nullable=False)
    ean = Column(String(50))

    # Inputs del cálculo
    costo = Column(Numeric(12, 2), nullable=False)
    moneda_costo = Column(String(3), nullable=False)
    iva = Column(Numeric(4, 2), nullable=False)
    comision_ml = Column(Numeric(5, 2), nullable=False)
    costo_envio = Column(Numeric(12, 2), default=0)
    precio_final = Column(Numeric(12, 2), nullable=False)

    # Resultados calculados
    markup_porcentaje = Column(Numeric(8, 2))
    limpio = Column(Numeric(12, 2))
    comision_total = Column(Numeric(12, 2))

    # Tipo de cambio usado en el cálculo
    tipo_cambio_usado = Column(Numeric(10, 2))

    # Cantidad para presupuesto/pedido
    cantidad = Column(Integer, default=0)

    # Precios de cuotas calculados automáticamente (JSONB)
    precios_cuotas = Column(JSONB, nullable=True)

    fecha_creacion = Column(DateTime, default=datetime.now)
    fecha_modificacion = Column(DateTime, default=datetime.now, onupdate=datetime.now)

    # Relación con usuario
    usuario = relationship("Usuario", back_populates="calculos_pricing")
