from sqlalchemy import Column, Integer, BigInteger, String, DateTime, Numeric, SmallInteger, Text, ForeignKey
from sqlalchemy.sql import func
from app.core.database import Base

class VentaML(Base):
    __tablename__ = "ventas_ml"

    id_venta = Column(BigInteger, primary_key=True, index=True)
    id_operacion = Column(BigInteger, unique=True, nullable=False, index=True)
    item_id = Column(Integer, ForeignKey('productos_erp.item_id'), index=True)
    fecha = Column(DateTime, nullable=False, index=True)
    marca = Column(String(100), index=True)
    categoria = Column(String(100), index=True)
    subcategoria = Column(String(100))
    subcat_id = Column(Integer)
    codigo_item = Column(String(100))
    descripcion = Column(Text)
    cantidad = Column(Integer, nullable=False)
    monto_unitario = Column(Numeric(12, 2))
    monto_total = Column(Numeric(12, 2), nullable=False)

    # Costos
    moneda_costo = Column(SmallInteger)  # 1=ARS, 2=USD
    costo_sin_iva = Column(Numeric(12, 4))
    iva = Column(Numeric(5, 2))
    cambio_al_momento = Column(Numeric(10, 4))

    # Info MercadoLibre
    ml_logistic_type = Column(String(50))
    ml_id = Column(BigInteger, index=True)
    ml_shipping_id = Column(BigInteger)
    ml_shipment_cost_seller = Column(Numeric(12, 2))
    ml_price_free_shipping = Column(Numeric(12, 2))
    ml_base_cost = Column(Numeric(12, 2))
    ml_pack_id = Column(BigInteger)
    price_list = Column(Integer)

    # Auditoría
    created_at = Column(DateTime(timezone=True), server_default=func.now())
    updated_at = Column(DateTime(timezone=True), server_default=func.now(), onupdate=func.now())


class MetricasVentasDiarias(Base):
    __tablename__ = "metricas_ventas_diarias"

    id = Column(Integer, primary_key=True, index=True)
    fecha = Column(DateTime, nullable=False, unique=True, index=True)
    total_ventas = Column(Integer, default=0)
    total_unidades = Column(Integer, default=0)
    monto_total_ars = Column(Numeric(15, 2), default=0)
    monto_total_usd = Column(Numeric(15, 2), default=0)
    costo_envios_total = Column(Numeric(15, 2), default=0)
    margen_bruto = Column(Numeric(15, 2))

    # Por tipo de logística
    ventas_full = Column(Integer, default=0)
    ventas_flex = Column(Integer, default=0)
    ventas_dropoff = Column(Integer, default=0)

    created_at = Column(DateTime(timezone=True), server_default=func.now())
    updated_at = Column(DateTime(timezone=True), server_default=func.now(), onupdate=func.now())


class MetricasVentasPorMarca(Base):
    __tablename__ = "metricas_ventas_por_marca"

    id = Column(Integer, primary_key=True, index=True)
    marca = Column(String(100), nullable=False, index=True)
    fecha = Column(DateTime, nullable=False, index=True)
    total_ventas = Column(Integer, default=0)
    total_unidades = Column(Integer, default=0)
    monto_total = Column(Numeric(15, 2), default=0)

    created_at = Column(DateTime(timezone=True), server_default=func.now())
    updated_at = Column(DateTime(timezone=True), server_default=func.now(), onupdate=func.now())


class MetricasVentasPorCategoria(Base):
    __tablename__ = "metricas_ventas_por_categoria"

    id = Column(Integer, primary_key=True, index=True)
    categoria = Column(String(100), nullable=False, index=True)
    subcategoria = Column(String(100))
    fecha = Column(DateTime, nullable=False, index=True)
    total_ventas = Column(Integer, default=0)
    total_unidades = Column(Integer, default=0)
    monto_total = Column(Numeric(15, 2), default=0)

    created_at = Column(DateTime(timezone=True), server_default=func.now())
    updated_at = Column(DateTime(timezone=True), server_default=func.now(), onupdate=func.now())


class ProductosPerformance(Base):
    __tablename__ = "productos_performance"

    id = Column(Integer, primary_key=True, index=True)
    item_id = Column(Integer, ForeignKey('productos_erp.item_id'), nullable=False, index=True)
    fecha_desde = Column(DateTime, nullable=False)
    fecha_hasta = Column(DateTime, nullable=False)

    # Métricas de ventas
    total_ventas = Column(Integer, default=0)
    total_unidades = Column(Integer, default=0)
    monto_total = Column(Numeric(15, 2), default=0)

    # Métricas de rentabilidad
    costo_total = Column(Numeric(15, 2))
    margen_bruto = Column(Numeric(15, 2))
    margen_porcentaje = Column(Numeric(5, 2))

    # Métricas de logística
    costo_envios_total = Column(Numeric(12, 2))

    created_at = Column(DateTime(timezone=True), server_default=func.now())
    updated_at = Column(DateTime(timezone=True), server_default=func.now(), onupdate=func.now())
