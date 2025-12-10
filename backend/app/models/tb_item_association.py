"""
Modelo para tbItemAssociation - Asociaciones de items
"""
from sqlalchemy import Column, Integer, Numeric, Boolean, DateTime
from sqlalchemy.sql import func
from app.core.database import Base


class TbItemAssociation(Base):
    """Tabla de asociaciones de items del ERP"""
    __tablename__ = "tb_item_association"

    # Primary Keys
    comp_id = Column(Integer, primary_key=True)
    itema_id = Column(Integer, primary_key=True, index=True)

    # Foreign keys a items
    item_id = Column(Integer, index=True)
    item_id_1 = Column(Integer, index=True)

    # Datos de la asociación
    iasso_qty = Column(Numeric(18, 4))
    itema_canDeleteInSO = Column(Boolean, default=True)
    itema_discountPercentage4PriceListSUM = Column(Numeric(18, 4))

    # Auditoría local
    created_at = Column(DateTime(timezone=True), server_default=func.now())
    updated_at = Column(DateTime(timezone=True), server_default=func.now(), onupdate=func.now())

    def __repr__(self):
        return f"<TbItemAssociation(itema_id={self.itema_id}, item_id={self.item_id}, item_id_1={self.item_id_1})>"
