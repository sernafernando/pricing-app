"""
Modelo para la tabla tb_rma_add_items (ítems adicionales agregados a un RMA detail)
Origen ERP: tbRMA_AddItems
"""

from sqlalchemy import Column, BigInteger, Integer, Numeric, Index
from app.core.database import Base


class TbRMAAddItems(Base):
    __tablename__ = "tb_rma_add_items"

    # Composite primary key
    comp_id = Column(Integer, primary_key=True)
    rmah_id = Column(BigInteger, primary_key=True)
    rmad_id = Column(BigInteger, primary_key=True)
    rmaai_id = Column(BigInteger, primary_key=True)

    # Data
    item_id = Column(BigInteger, nullable=True)
    rmaai_qty = Column(Numeric(18, 6), nullable=True)
    rmaai_price = Column(Numeric(18, 4), nullable=True)
    curr_id = Column(Integer, nullable=True)

    __table_args__ = (
        Index("idx_rmaai_item_id", "item_id"),
        Index("idx_rmaai_rmah_id", "rmah_id"),
        Index("idx_rmaai_rmad_id", "rmad_id"),
    )

    def __repr__(self) -> str:
        return f"<TbRMAAddItems(rmaai_id={self.rmaai_id}, rmad_id={self.rmad_id}, item_id={self.item_id})>"
