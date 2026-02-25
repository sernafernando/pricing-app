"""
Modelo para la tabla tb_rma_supplier_cn_pending (notas de crédito pendientes de proveedor)
Origen ERP: tbRMA_SupplierCreditNotePending
"""

from sqlalchemy import Column, BigInteger, Integer, Numeric, Boolean, Index
from app.core.database import Base


class TbRMASupplierCNPending(Base):
    __tablename__ = "tb_rma_supplier_cn_pending"

    # Primary key
    comp_id = Column(Integer, primary_key=True)
    rmanc_id = Column(BigInteger, primary_key=True)

    # Foreign keys
    rmah_id = Column(BigInteger, nullable=True)
    rmad_id = Column(BigInteger, nullable=True)
    supp_id = Column(BigInteger, nullable=True)
    item_id = Column(BigInteger, nullable=True)
    ct_transaction = Column(BigInteger, nullable=True)
    curr_id = Column(Integer, nullable=True)
    stor_id = Column(Integer, nullable=True)

    # Data
    rmanc_price = Column(Numeric(18, 6), nullable=True)
    rmanc_qty = Column(Numeric(18, 4), nullable=True)
    rmanc_isProcessed = Column(Boolean, nullable=True)

    __table_args__ = (
        Index("idx_rmanc_rmah_id", "rmah_id"),
        Index("idx_rmanc_rmad_id", "rmad_id"),
        Index("idx_rmanc_supp_id", "supp_id"),
        Index("idx_rmanc_item_id", "item_id"),
    )

    def __repr__(self) -> str:
        return f"<TbRMASupplierCNPending(rmanc_id={self.rmanc_id}, rmah_id={self.rmah_id}, item_id={self.item_id})>"
