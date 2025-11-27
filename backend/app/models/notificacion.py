from sqlalchemy import Column, Integer, String, Boolean, DateTime, Text, Numeric, BigInteger
from sqlalchemy.sql import func
from app.core.database import Base

class Notificacion(Base):
    __tablename__ = "notificaciones"

    id = Column(Integer, primary_key=True, index=True)
    tipo = Column(String(50), nullable=False, index=True)  # markup_bajo, stock_bajo, precio_desactualizado, etc.
    item_id = Column(Integer, nullable=True, index=True)
    id_operacion = Column(BigInteger, nullable=True)  # ID de operación ML
    codigo_producto = Column(String(100), nullable=True)
    descripcion_producto = Column(String(500), nullable=True)
    mensaje = Column(Text, nullable=False)

    # Campos específicos para notificaciones de markup
    markup_real = Column(Numeric(10, 2), nullable=True)
    markup_objetivo = Column(Numeric(10, 2), nullable=True)
    monto_venta = Column(Numeric(12, 2), nullable=True)
    fecha_venta = Column(DateTime(timezone=True), nullable=True)

    # Control de lectura
    leida = Column(Boolean, default=False, nullable=False, index=True)
    fecha_creacion = Column(DateTime(timezone=True), server_default=func.now(), nullable=False, index=True)
    fecha_lectura = Column(DateTime(timezone=True), nullable=True)
