"""
Modelo para tbItemStorage — stock de items por depósito en el ERP.
PK: (comp_id, stor_id, item_id) — un item puede estar en varios depósitos.
"""

from sqlalchemy import Column, Integer, Numeric, String, DateTime
from sqlalchemy.sql import func
from app.core.database import Base


class TbItemStorage(Base):
    __tablename__ = "tb_item_storage"

    # Primary keys (compuesta: empresa + depósito + item)
    comp_id = Column(Integer, primary_key=True)
    stor_id = Column(Integer, primary_key=True, index=True)
    item_id = Column(Integer, primary_key=True, index=True)

    # Stock actual
    itst_cant = Column(Numeric(18, 4))

    # Ubicaciones físicas
    itst_PickingLocation = Column(String(100))
    itst_StorageLocation = Column(String(100))

    # Auditoría del ERP
    itst_cd = Column(DateTime)
    itst_updateByInTransitStock = Column(DateTime)
    itst_LastAvailableInRelalculation = Column(DateTime, index=True)
    itst_LastQTYAtQuery = Column(DateTime)

    # Auditoría local
    created_at = Column(DateTime(timezone=True), server_default=func.now())
    updated_at = Column(DateTime(timezone=True), server_default=func.now(), onupdate=func.now())

    def __repr__(self):
        return f"<TbItemStorage(stor_id={self.stor_id}, item_id={self.item_id}, cant={self.itst_cant})>"
