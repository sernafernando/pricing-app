"""
Modelo para la tabla tb_item_serials (números de serie de items)
"""
from sqlalchemy import Column, BigInteger, Integer, String, DateTime, Boolean
from app.core.database import Base


class TbItemSerial(Base):
    __tablename__ = "tb_item_serials"

    # Composite primary key
    comp_id = Column(Integer, primary_key=True)
    is_id = Column(BigInteger, primary_key=True)
    bra_id = Column(Integer, primary_key=True)

    # Foreign keys
    ct_transaction = Column(BigInteger, nullable=True)
    it_transaction = Column(BigInteger, nullable=True)
    item_id = Column(Integer, nullable=True)
    stor_id = Column(Integer, nullable=True)

    # Serial data
    is_serial = Column(String(100), nullable=True, index=True)  # Número de serie
    is_cd = Column(DateTime, nullable=True, index=True)  # Fecha de creación
    is_available = Column(Boolean, nullable=True)  # Disponible
    is_guid = Column(String(100), nullable=True)  # GUID
    is_IsOwnGeneration = Column('is_isowngeneration', Boolean, nullable=True)  # Generación propia
    is_checked = Column(Boolean, nullable=True)  # Chequeado
    is_printed = Column(Boolean, nullable=True)  # Impreso

    def __repr__(self):
        return f"<TbItemSerial(is_id={self.is_id}, is_serial={self.is_serial}, item_id={self.item_id})>"
