"""
Modelo para la tabla tb_storage (depósitos/almacenes)
Origen ERP: tbStorage
"""

from sqlalchemy import Column, Integer, String, Boolean
from app.core.database import Base


class TbStorage(Base):
    __tablename__ = "tb_storage"

    # Composite primary key
    comp_id = Column(Integer, primary_key=True)
    stor_id = Column(Integer, primary_key=True)

    # Datos del depósito
    stor_desc = Column(String(255), nullable=True)
    bra_id = Column(Integer, nullable=True)
    stor_disabled = Column(Boolean, nullable=True)

    def __repr__(self) -> str:
        return f"<TbStorage(stor_id={self.stor_id}, stor_desc={self.stor_desc})>"
