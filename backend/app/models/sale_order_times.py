"""
Modelo para tbSaleOrderTimes del ERP
Registra las transacciones/cambios de estado de las órdenes de venta
"""

from sqlalchemy import Column, Integer, BigInteger, DateTime, PrimaryKeyConstraint, Index
from app.core.database import Base


class SaleOrderTimes(Base):
    """
    Modelo para tbSaleOrderTimes del ERP
    Tabla acumulativa que registra todas las transacciones de una sale order.

    ssot_id (Estado de la transacción):
    - 10: Creación del Pedido
    - 15: Modificación del Pedido
    - 20: Envío a Preparación
    - 30: Comienzo de Preparación
    - 40: Cierre del Pedido ← CLAVE para filtrar pedidos cerrados
    - 50: Procesamiento del Pedido
    - 60: Salida del Pedido
    - 70: Entrega del Pedido

    Uso principal: Detectar pedidos cerrados (ssot_id = 40) aunque tengan ssos_id = 20
    """

    __tablename__ = "tb_sale_order_times"
    __table_args__ = (
        PrimaryKeyConstraint("comp_id", "bra_id", "soh_id", "sot_id"),
        Index("ix_sale_order_times_soh", "comp_id", "bra_id", "soh_id"),
        Index("ix_sale_order_times_ssot", "ssot_id"),
        Index("ix_sale_order_times_cd", "sot_cd"),
    )

    # Composite Primary Key
    comp_id = Column(Integer, nullable=False)
    bra_id = Column(Integer, nullable=False)
    soh_id = Column(BigInteger, nullable=False, index=True)
    sot_id = Column(BigInteger, nullable=False)  # ID único de la transacción

    # Datos de la transacción
    sot_cd = Column(DateTime, index=True)  # Fecha/hora de la transacción
    ssot_id = Column(Integer, nullable=False, index=True)  # Tipo de transacción (10, 20, 40, etc)
    user_id = Column(Integer)  # Usuario que ejecutó la transacción
