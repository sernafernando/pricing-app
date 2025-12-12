from sqlalchemy import Column, Integer, String, Boolean, DateTime, Text, Numeric, BigInteger, ForeignKey
from sqlalchemy.orm import relationship
from sqlalchemy.sql import func
from app.core.database import Base

class Notificacion(Base):
    __tablename__ = "notificaciones"

    id = Column(Integer, primary_key=True, index=True)
    user_id = Column(Integer, ForeignKey('usuarios.id', ondelete='CASCADE'), nullable=True, index=True)
    tipo = Column(String(50), nullable=False, index=True)  # markup_bajo, stock_bajo, precio_desactualizado, etc.
    item_id = Column(Integer, nullable=True, index=True)
    id_operacion = Column(BigInteger, nullable=True)  # ID de operación ML
    ml_id = Column(String(50), nullable=True, index=True)  # ML_id de la orden
    pack_id = Column(BigInteger, nullable=True, index=True)  # Pack ID de ML para URL
    codigo_producto = Column(String(100), nullable=True)
    descripcion_producto = Column(String(500), nullable=True)
    mensaje = Column(Text, nullable=False)

    # Campos específicos para notificaciones de markup
    markup_real = Column(Numeric(10, 2), nullable=True)
    markup_objetivo = Column(Numeric(10, 2), nullable=True)
    monto_venta = Column(Numeric(12, 2), nullable=True)
    fecha_venta = Column(DateTime(timezone=True), nullable=True)

    # Campos adicionales para detalle
    pm = Column(String(100), nullable=True)  # Product Manager asignado a la marca
    costo_operacion = Column(Numeric(12, 2), nullable=True)  # Costo al momento de la venta
    costo_actual = Column(Numeric(12, 2), nullable=True)  # Costo actual
    precio_venta_unitario = Column(Numeric(12, 2), nullable=True)  # Precio unitario
    precio_publicacion = Column(Numeric(12, 2), nullable=True)  # Precio en publicación ML
    tipo_publicacion = Column(String(50), nullable=True)  # classic, gold, premium
    comision_ml = Column(Numeric(12, 2), nullable=True)  # Comisión ML
    iva_porcentaje = Column(Numeric(5, 2), nullable=True)  # % de IVA
    cantidad = Column(Integer, nullable=True)  # Cantidad vendida
    costo_envio = Column(Numeric(12, 2), nullable=True)  # Costo de envío

    # Tipos de cambio usados
    tipo_cambio_operacion = Column(Numeric(12, 4), nullable=True)  # TC usado para costo_operacion
    tipo_cambio_actual = Column(Numeric(12, 4), nullable=True)  # TC usado para costo_actual

    # Control de lectura
    leida = Column(Boolean, default=False, nullable=False, index=True)
    fecha_creacion = Column(DateTime(timezone=True), server_default=func.now(), nullable=False, index=True)
    fecha_lectura = Column(DateTime(timezone=True), nullable=True)

    # Relaciones
    usuario = relationship("Usuario", backref="notificaciones")
