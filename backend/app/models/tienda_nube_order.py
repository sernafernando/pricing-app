from sqlalchemy import Column, Integer, BigInteger, DateTime, Boolean, Text, PrimaryKeyConstraint
from app.core.database import Base


class TiendaNubeOrder(Base):
    """
    Modelo para tb_tiendanube_orders
    Órdenes de TiendaNube sincronizadas desde el ERP
    """

    __tablename__ = "tb_tiendanube_orders"
    __table_args__ = (PrimaryKeyConstraint("comp_id", "tno_id"),)

    # Primary Key
    comp_id = Column(Integer, nullable=False, index=True)
    tno_id = Column(BigInteger, nullable=False, index=True)

    # Campos principales
    tno_cd = Column(DateTime)
    tn_id = Column(Integer)  # ID de la tienda en TiendaNube
    tno_orderid = Column(Integer, index=True)  # Número de orden de TN
    tno_json = Column(Text)  # JSON completo de la orden desde TN API
    bra_id = Column(Integer, index=True)
    soh_id = Column(BigInteger, index=True)  # Relación con sale_order_header
    cust_id = Column(Integer)
    tno_iscancelled = Column(Boolean)

    # Timestamps
    created_at = Column(DateTime)
    updated_at = Column(DateTime)

    def __repr__(self):
        return f"<TiendaNubeOrder(tno_id={self.tno_id}, tno_orderid={self.tno_orderid}, soh_id={self.soh_id})>"
