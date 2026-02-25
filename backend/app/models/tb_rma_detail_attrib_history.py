"""
Modelo para la tabla tb_rma_detail_attrib_history (historial de atributos de RMA detail)
Origen ERP: tbRMA_Detail_AttributesHistory
"""

from sqlalchemy import Column, BigInteger, Integer, DateTime, Index
from app.core.database import Base


class TbRMADetailAttribHistory(Base):
    __tablename__ = "tb_rma_detail_attrib_history"

    # Primary key
    comp_id = Column(Integer, primary_key=True)
    rmadh_id = Column(BigInteger, primary_key=True)

    # Foreign keys
    rmah_id = Column(BigInteger, nullable=True)
    rmad_id = Column(BigInteger, nullable=True)
    user_id = Column(BigInteger, nullable=True)
    srpt_id = Column(Integer, nullable=True)
    rmas_id = Column(Integer, nullable=True)
    rmap_id = Column(Integer, nullable=True)
    rmaw_id = Column(Integer, nullable=True)
    rmamt_id = Column(Integer, nullable=True)

    # Date
    rmadh_cd = Column(DateTime, nullable=True)

    __table_args__ = (
        Index("idx_rmadh_rmah_id", "rmah_id"),
        Index("idx_rmadh_rmad_id", "rmad_id"),
        Index("idx_rmadh_cd", "rmadh_cd"),
    )

    def __repr__(self) -> str:
        return f"<TbRMADetailAttribHistory(rmadh_id={self.rmadh_id}, rmad_id={self.rmad_id})>"
