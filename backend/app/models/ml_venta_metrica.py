"""
Modelo para métricas precalculadas de ventas ML
Contiene todos los cálculos de markup, costos, comisiones, etc.
Se actualiza mediante un script de agregación que lee de ml_orders + commercial_transactions
"""
from sqlalchemy import Column, Integer, BigInteger, String, Numeric, DateTime, Date, Text
from sqlalchemy.sql import func
from app.core.database import Base


class MLVentaMetrica(Base):
    """
    Tabla de métricas precalculadas para ventas de MercadoLibre

    Flujo de cálculo:
    1. Monto total de venta (precio * cantidad)
    2. Comisión ML (según tipo de lista y categoría)
    3. Costo de envío ML
    4. Monto limpio = monto total - comisión ML - costo envío
    5. Costo del producto sin IVA (desde commercial_transaction)
    6. Costo total = costo sin IVA + costo envío
    7. Ganancia = monto limpio - costo sin IVA
    8. Markup = (ganancia / costo sin IVA) * 100
    """
    __tablename__ = "ml_ventas_metricas"

    # Primary Key
    id = Column(Integer, primary_key=True, index=True)

    # Identificadores de la venta
    id_operacion = Column(BigInteger, unique=True, index=True, nullable=False)  # ID único de la orden ML
    ml_order_id = Column(String(50), index=True)  # ID de la orden en ml_orders_header (puede contener caracteres)
    pack_id = Column(BigInteger, index=True)  # Para órdenes agrupadas

    # Información del producto
    item_id = Column(Integer, index=True)
    codigo = Column(String(100))
    descripcion = Column(Text)
    marca = Column(String(255), index=True)
    categoria = Column(String(255), index=True)
    subcategoria = Column(String(255))

    # Fecha y timing
    fecha_venta = Column(DateTime(timezone=True), index=True, nullable=False)
    fecha_calculo = Column(Date, index=True)  # Fecha del snapshot/cálculo

    # Cantidades
    cantidad = Column(Integer, nullable=False)

    # Montos de venta (todos sin IVA)
    monto_unitario = Column(Numeric(18, 2))  # Precio unitario de venta
    monto_total = Column(Numeric(18, 2), nullable=False)  # Precio total de venta (cantidad * unitario)

    # Cotización del momento
    cotizacion_dolar = Column(Numeric(10, 4))  # Cotización USD al momento de la venta

    # Costos del producto (sin IVA)
    costo_unitario_sin_iva = Column(Numeric(18, 6))  # Costo unitario del producto
    costo_total_sin_iva = Column(Numeric(18, 2))  # Costo total del producto (cantidad * unitario)
    moneda_costo = Column(String(10))  # USD o ARS

    # Comisiones y costos ML
    tipo_lista = Column(String(50))  # gold_pro, gold_special, etc.
    porcentaje_comision_ml = Column(Numeric(5, 2))  # % de comisión ML
    comision_ml = Column(Numeric(18, 2))  # Monto de comisión ML
    costo_envio_ml = Column(Numeric(18, 2))  # Costo de envío que paga el vendedor
    tipo_logistica = Column(String(50))  # full, flex, colecta, retiro

    # Cálculos finales
    monto_limpio = Column(Numeric(18, 2))  # monto_total - comision_ml - costo_envio_ml
    costo_total = Column(Numeric(18, 2))  # costo_total_sin_iva + costo_envio_ml
    ganancia = Column(Numeric(18, 2))  # monto_limpio - costo_total_sin_iva
    markup_porcentaje = Column(Numeric(10, 2))  # (ganancia / costo_total_sin_iva) * 100

    # Información adicional
    prli_id = Column(Integer)  # ID de lista de precios del ERP
    mla_id = Column(String(50))  # MLA ID de la publicación
    mlp_official_store_id = Column(Integer, index=True)  # ID de tienda oficial ML (57997=Gauss, 2645=TP-Link, etc.)

    # Auditoría
    created_at = Column(DateTime(timezone=True), server_default=func.now())
    updated_at = Column(DateTime(timezone=True), server_default=func.now(), onupdate=func.now())

    def __repr__(self):
        return (
            f"<MLVentaMetrica("
            f"id_operacion={self.id_operacion}, "
            f"fecha={self.fecha_venta}, "
            f"marca={self.marca}, "
            f"monto_total={self.monto_total}, "
            f"markup={self.markup_porcentaje}%"
            f")>"
        )
