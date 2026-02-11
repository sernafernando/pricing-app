"""
Modelo para tb_pedidos_export
Tabla simple que guarda TAL CUAL los datos del Export 87
"""

from sqlalchemy import Column, Integer, Numeric, Boolean, DateTime, Text
from sqlalchemy.sql import func
from app.core.database import Base


class PedidoExport(Base):
    __tablename__ = "tb_pedidos_export"

    # PK compuesta
    id_pedido = Column(Integer, primary_key=True)
    item_id = Column(Integer, primary_key=True)

    # Cliente
    id_cliente = Column(Integer)
    nombre_cliente = Column(Text)
    user_id = Column(Integer, index=True)  # 50021=TN, 50006=ML

    # Item
    cantidad = Column(Numeric(10, 2))
    item_code = Column(Text)  # EAN
    item_desc = Column(Text)  # Descripción del producto

    # Envío
    tipo_envio = Column(Text)
    direccion_envio = Column(Text)
    fecha_envio = Column(DateTime)

    # Observaciones
    observaciones = Column(Text)

    # TiendaNube
    orden_tn = Column(Text, index=True)
    order_id_tn = Column(Text, index=True)

    # Control
    activo = Column(Boolean, default=True, index=True)
    fecha_sync = Column(DateTime, server_default=func.now())

    def __repr__(self):
        return f"<PedidoExport(id_pedido={self.id_pedido}, item_id={self.item_id}, orden_tn={self.orden_tn})>"
