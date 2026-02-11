"""
Modelo para cache de pedidos en preparación.
Se actualiza cada 5 minutos desde la query 67 del ERP via gbp-parser.
"""

from sqlalchemy import Column, Integer, String, Numeric, DateTime
from sqlalchemy.sql import func
from app.core.database import Base


class PedidoPreparacionCache(Base):
    """
    Cache de pedidos en preparación.
    Datos vienen de la query 67 del ERP via gbp-parser.

    Columnas de la query:
    - item_id
    - item_code
    - item_desc
    - cantidad (SUM de mlo_quantity)
    - ML_logistic_type (Turbo si MLshipping_method_id=515282, sino ml_logistic_type)
    - PreparaPaquete (COUNT de ML_pack_id)
    """

    __tablename__ = "pedido_preparacion_cache"

    id = Column(Integer, primary_key=True, autoincrement=True)
    item_id = Column(Integer, index=True)
    item_code = Column(String(100))
    item_desc = Column(String(500))
    cantidad = Column(Numeric(18, 2), default=0)
    ml_logistic_type = Column(String(50))
    prepara_paquete = Column(Integer, default=0)

    # Metadata
    updated_at = Column(DateTime, server_default=func.now(), onupdate=func.now())

    def __repr__(self):
        return f"<PedidoPreparacionCache item_id={self.item_id} cantidad={self.cantidad}>"
