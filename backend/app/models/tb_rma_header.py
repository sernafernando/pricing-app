"""
Modelo para la tabla tb_rma_header (cabecera de RMA/garantías)
Origen ERP: tbRMA_Header
"""

from sqlalchemy import Column, BigInteger, Integer, String, DateTime, Boolean, Index
from app.core.database import Base


class TbRMAHeader(Base):
    __tablename__ = "tb_rma_header"

    # Composite primary key
    comp_id = Column(Integer, primary_key=True)
    rmah_id = Column(BigInteger, primary_key=True)
    bra_id = Column(Integer, primary_key=True)

    # Foreign keys
    cust_id = Column(BigInteger, nullable=True)
    supp_id = Column(BigInteger, nullable=True)
    rmap_id = Column(Integer, nullable=True)
    user_id_assigned = Column(BigInteger, nullable=True)

    # Dates
    rmah_cd = Column(DateTime, nullable=True)
    rmah_isEditingCD = Column(DateTime, nullable=True)

    # Flags
    rmah_isEditing = Column(Boolean, nullable=True)
    rmah_isInSuppplier = Column(Boolean, nullable=True)

    # Notes
    rmah_note1 = Column(String(4000), nullable=True)
    rmah_note2 = Column(String(4000), nullable=True)

    __table_args__ = (
        Index("idx_rmah_cust_id", "cust_id"),
        Index("idx_rmah_supp_id", "supp_id"),
        Index("idx_rmah_cd", "rmah_cd"),
        Index("idx_rmah_user_assigned", "user_id_assigned"),
    )

    def __repr__(self) -> str:
        return f"<TbRMAHeader(rmah_id={self.rmah_id}, cust_id={self.cust_id}, bra_id={self.bra_id})>"
