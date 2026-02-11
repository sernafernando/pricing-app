"""
Modelo para métricas precalculadas de ventas fuera de MercadoLibre
Contiene todos los cálculos de markup, costos, etc.
Se actualiza mediante un script de agregación que lee de tb_item_transactions + tb_commercial_transactions
"""

from sqlalchemy import Column, Integer, BigInteger, String, Numeric, DateTime, Date, Boolean, Text
from sqlalchemy.sql import func
from app.core.database import Base


class VentaFueraMLMetrica(Base):
    """
    Tabla de métricas precalculadas para ventas por fuera de MercadoLibre

    Flujo de cálculo:
    1. Monto total de venta (precio * cantidad)
    2. Costo del producto sin IVA (desde histórico de costos)
    3. Ganancia = monto - costo
    4. Markup = (monto / costo) - 1 (sin comisión porque es venta directa)
    """

    __tablename__ = "ventas_fuera_ml_metricas"

    # Primary Key
    id = Column(Integer, primary_key=True, index=True)

    # Identificador de la transacción
    it_transaction = Column(BigInteger, unique=True, index=True, nullable=False)
    ct_transaction = Column(BigInteger, index=True)

    # Información del producto
    item_id = Column(Integer, index=True)
    codigo = Column(String(100))
    descripcion = Column(Text)
    marca = Column(String(255), index=True)
    categoria = Column(String(255), index=True)
    subcategoria = Column(String(255))

    # Sucursal y vendedor
    bra_id = Column(Integer, index=True)
    sucursal = Column(String(255), index=True)
    sm_id = Column(Integer, index=True)
    vendedor = Column(String(255), index=True)

    # Cliente
    cust_id = Column(Integer, index=True)
    cliente = Column(String(255))

    # Comprobante
    df_id = Column(Integer)
    tipo_comprobante = Column(String(100))
    numero_comprobante = Column(String(50))

    # Fecha
    fecha_venta = Column(DateTime(timezone=True), index=True, nullable=False)
    fecha_calculo = Column(Date, index=True)

    # Tipo de operación
    sd_id = Column(Integer)  # 1,4,21,56 = venta, 3,6,23,66 = devolución
    signo = Column(Integer)  # +1 o -1

    # Cantidades
    cantidad = Column(Numeric(18, 4), nullable=False)

    # Montos de venta (sin IVA)
    monto_unitario = Column(Numeric(18, 2))
    monto_total = Column(Numeric(18, 2), nullable=False)

    # IVA
    iva_porcentaje = Column(Numeric(5, 2))
    monto_iva = Column(Numeric(18, 2))
    monto_con_iva = Column(Numeric(18, 2))

    # Costos del producto (sin IVA)
    costo_unitario = Column(Numeric(18, 6))
    costo_total = Column(Numeric(18, 2))
    moneda_costo = Column(String(10))  # USD o ARS
    cotizacion_dolar = Column(Numeric(10, 4))

    # Cálculos finales
    ganancia = Column(Numeric(18, 2))  # monto_total - costo_total
    markup_porcentaje = Column(Numeric(10, 2))  # (monto_total / costo_total) - 1

    # Flag para indicar si es un combo
    es_combo = Column(Boolean, default=False)
    combo_group_id = Column(BigInteger, index=True)

    # Auditoría
    created_at = Column(DateTime(timezone=True), server_default=func.now())
    updated_at = Column(DateTime(timezone=True), server_default=func.now(), onupdate=func.now())

    def __repr__(self):
        return (
            f"<VentaFueraMLMetrica("
            f"it_transaction={self.it_transaction}, "
            f"fecha={self.fecha_venta}, "
            f"marca={self.marca}, "
            f"monto_total={self.monto_total}, "
            f"markup={self.markup_porcentaje}%"
            f")>"
        )
