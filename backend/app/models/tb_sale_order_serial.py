"""
Modelo para la tabla tb_sale_order_serials (serials vinculados a sale orders)
Origen ERP: tbSaleOrderSerials
"""

from sqlalchemy import Column, BigInteger, Integer, String, Index
from app.core.database import Base


class TbSaleOrderSerial(Base):
    __tablename__ = "tb_sale_order_serials"

    # Composite primary key
    comp_id = Column(Integer, primary_key=True)
    bra_id = Column(Integer, primary_key=True)
    sose_id = Column(BigInteger, primary_key=True)

    # Foreign keys
    is_id = Column(BigInteger, nullable=True)
    soh_id = Column(BigInteger, nullable=True)

    # GUID
    sose_guid = Column(String(100), nullable=True)

    __table_args__ = (
        Index("idx_sose_is_id", "is_id"),
        Index("idx_sose_soh_id", "soh_id"),
    )

    def __repr__(self) -> str:
        return f"<TbSaleOrderSerial(sose_id={self.sose_id}, is_id={self.is_id}, soh_id={self.soh_id})>"
