"""
Model for pre-calculated TP-Link sales metrics.
Clone of ml_venta_metrica.py with __tablename__ = "tplink_ventas_metricas".
Written exclusively by agregar_metricas_tplink.py (store 2645, coslis_id=8).
ML model/jobs are byte-for-byte unmodified.
"""

from sqlalchemy import Column, Integer, BigInteger, String, Numeric, DateTime, Date, Text, Boolean
from sqlalchemy.sql import func
from app.core.database import Base


class TplinkVentaMetrica(Base):
    """
    Table of pre-calculated metrics for TP-Link MercadoLibre sales (store 2645).

    Calculation flow (mirrors MLVentaMetrica):
    1. Total sale amount (price * quantity)
    2. ML commission (by listing type and category)
    3. ML shipping cost
    4. Net amount = total - ML commission - shipping
    5. Product cost without VAT (from item_cost_list_history, coslis_id=8)
    6. Total cost = cost without VAT + shipping cost
    7. Profit = net amount - cost without VAT
    8. Markup = (profit / cost without VAT) * 100
    """

    __tablename__ = "tplink_ventas_metricas"

    # Primary Key
    id = Column(Integer, primary_key=True, index=True)

    # Sale identifiers
    id_operacion = Column(BigInteger, unique=True, index=True, nullable=False)
    ml_order_id = Column(String(50), index=True)
    pack_id = Column(BigInteger, index=True)

    # Product information
    item_id = Column(Integer, index=True)
    codigo = Column(String(100))
    descripcion = Column(Text)
    marca = Column(String(255), index=True)
    categoria = Column(String(255), index=True)
    subcategoria = Column(String(255))

    # Date and timing
    fecha_venta = Column(DateTime(timezone=True), index=True, nullable=False)
    fecha_calculo = Column(Date, index=True)

    # Quantities
    cantidad = Column(Integer, nullable=False)

    # Sale amounts (without VAT)
    monto_unitario = Column(Numeric(18, 2))
    monto_total = Column(Numeric(18, 2), nullable=False)

    # Exchange rate at sale time
    cotizacion_dolar = Column(Numeric(10, 4))

    # Product costs (without VAT) — from coslis_id=8
    costo_unitario_sin_iva = Column(Numeric(18, 6))
    costo_total_sin_iva = Column(Numeric(18, 2))
    moneda_costo = Column(String(10))

    # ML commissions and costs
    tipo_lista = Column(String(50))
    porcentaje_comision_ml = Column(Numeric(5, 2))
    comision_ml = Column(Numeric(18, 2))
    costo_envio_ml = Column(Numeric(18, 2))
    tipo_logistica = Column(String(50))

    # Final calculations
    monto_limpio = Column(Numeric(18, 2))
    costo_total = Column(Numeric(18, 2))
    ganancia = Column(Numeric(18, 2))
    markup_porcentaje = Column(Numeric(10, 2))
    offset_flex = Column(Numeric(18, 2), default=0)

    # Additional information
    prli_id = Column(Integer)
    mla_id = Column(String(50))
    mlp_official_store_id = Column(Integer, index=True)  # Always 2645 for TP-Link (kept for audit)

    # Cancellation state (reconciled against mlwebhook.ml_cancelled_orders)
    is_cancelled = Column(Boolean, nullable=False, server_default="false", index=True)
    fecha_cancelacion = Column(DateTime(timezone=True))

    # Audit timestamps
    created_at = Column(DateTime(timezone=True), server_default=func.now())
    updated_at = Column(DateTime(timezone=True), server_default=func.now(), onupdate=func.now())

    def __repr__(self) -> str:
        return (
            f"<TplinkVentaMetrica("
            f"id_operacion={self.id_operacion}, "
            f"fecha={self.fecha_venta}, "
            f"marca={self.marca}, "
            f"monto_total={self.monto_total}, "
            f"markup={self.markup_porcentaje}%"
            f")>"
        )
