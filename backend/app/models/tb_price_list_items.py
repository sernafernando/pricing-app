"""
Modelo para tbPriceListItems — registros de listas de precios del ERP.
PK: (comp_id, prli_id, item_id) — un item puede estar en varias listas.
"""

from sqlalchemy import Column, Integer, Numeric, Boolean, DateTime
from sqlalchemy.sql import func
from app.core.database import Base


class TbPriceListItems(Base):
    __tablename__ = "tb_price_list_items"

    # Primary keys (compuesta: empresa + lista + item)
    comp_id = Column(Integer, primary_key=True)
    prli_id = Column(Integer, primary_key=True, index=True)
    item_id = Column(Integer, primary_key=True, index=True)

    # Datos del precio
    prli_price = Column(Numeric(18, 4))
    curr_id = Column(Integer)
    bra_id = Column(Integer)

    # Histórico (precio/moneda anterior antes del último update)
    prli_price_PreLastUpdate = Column(Numeric(18, 4))
    curr_id_PreLastUpdate = Column(Integer)

    # Auditoría del ERP
    prli_cd = Column(DateTime, index=True)
    prli_updatedAt = Column(DateTime, index=True)
    prli_triggerUpdateCD = Column(DateTime)
    prli_lastModuleUpdate = Column(Integer)
    prli_lastRuleUpdate = Column(DateTime)
    user_id_lastUpdate = Column(Integer)
    prli_disabled4Rules = Column(Boolean)

    # Auditoría local
    created_at = Column(DateTime(timezone=True), server_default=func.now())
    updated_at = Column(DateTime(timezone=True), server_default=func.now(), onupdate=func.now())

    def __repr__(self):
        return f"<TbPriceListItems(prli_id={self.prli_id}, item_id={self.item_id}, price={self.prli_price})>"
