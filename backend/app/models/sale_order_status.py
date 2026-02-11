"""
Modelo para tb_sale_order_status
Estados de pedidos sincronizados desde vwSaleOrderStatus del ERP
"""

from sqlalchemy import Column, Integer, String, Boolean
from app.core.database import Base


class SaleOrderStatus(Base):
    """
    Estados de pedidos (ssos_id).
    Sincronizado desde vwSaleOrderStatus del ERP.
    """

    __tablename__ = "tb_sale_order_status"

    ssos_id = Column(Integer, primary_key=True)
    ssos_name = Column(String(100), nullable=False)
    ssos_description = Column(String(255))
    ssos_is_active = Column(Boolean, default=True)

    # Campos para categorización (definidos localmente)
    ssos_category = Column(String(50))  # 'pendiente', 'en_proceso', 'completado', 'cancelado'
    ssos_color = Column(String(20))  # Para UI
    ssos_order = Column(Integer)  # Orden de visualización

    def __repr__(self):
        return f"<SaleOrderStatus(ssos_id={self.ssos_id}, name='{self.ssos_name}')>"
