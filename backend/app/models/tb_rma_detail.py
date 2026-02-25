"""
Modelo para la tabla tb_rma_detail (detalle de RMA/garantías)
Origen ERP: tbRMA_Detail
"""

from sqlalchemy import Column, BigInteger, Integer, String, DateTime, Numeric, Boolean, Index
from app.core.database import Base


class TbRMADetail(Base):
    __tablename__ = "tb_rma_detail"

    # Composite primary key
    comp_id = Column(Integer, primary_key=True)
    rmad_id = Column(BigInteger, primary_key=True)
    bra_id = Column(Integer, primary_key=True)

    # Foreign keys
    rmah_id = Column(BigInteger, nullable=True)
    item_id = Column(BigInteger, nullable=True)
    it_transaction = Column(BigInteger, nullable=True)
    stor_id = Column(Integer, nullable=True)
    curr_id = Column(Integer, nullable=True)
    is_id = Column(BigInteger, nullable=True)
    supp_id = Column(BigInteger, nullable=True)
    rmas_id = Column(Integer, nullable=True)
    rmap_id = Column(Integer, nullable=True)
    rmafp_id = Column(Integer, nullable=True)
    rmamt_id = Column(Integer, nullable=True)
    rmaw_id = Column(Integer, nullable=True)
    rmafailP_id = Column(Integer, nullable=True)
    srpt_id = Column(Integer, nullable=True)
    case_id = Column(BigInteger, nullable=True)
    rmafp_tax_id = Column(Integer, nullable=True)

    # Item replacement
    item_id4Replacement = Column(BigInteger, nullable=True)
    stor_id4Replacement = Column(Integer, nullable=True)

    # Credit note
    it_transaction_CN = Column(BigInteger, nullable=True)
    df_id4CreditNote = Column(BigInteger, nullable=True)
    it_transaction_Origin = Column(BigInteger, nullable=True)

    # Manual / serial
    rmad_Manual = Column(String(255), nullable=True)
    rmad_serial = Column(String(255), nullable=True)

    # Precios
    rmad_originalPrice = Column(Numeric(18, 6), nullable=True)
    rmad_qty = Column(Numeric(18, 5), nullable=True)
    rmafp_Price = Column(Numeric(18, 6), nullable=True)
    rmafp_curr_id = Column(Integer, nullable=True)
    rmad_up2Price = Column(Numeric(18, 6), nullable=True)

    # Reception
    user_id_Reception = Column(BigInteger, nullable=True)
    rmad_Date_Reception = Column(DateTime, nullable=True)
    rmad_ReceptionNote = Column(String(2000), nullable=True)

    # Diagnostic
    user_id_Diagnostic = Column(BigInteger, nullable=True)
    rmad_Date_Diagnostic = Column(DateTime, nullable=True)
    rmad_DiagnosticNote = Column(String(2000), nullable=True)

    # Processing
    user_id_Proc = Column(BigInteger, nullable=True)
    rmad_Date_Proc = Column(DateTime, nullable=True)
    rmad_ProcNote = Column(String(2000), nullable=True)

    # Delivery
    user_id_Delivery = Column(BigInteger, nullable=True)
    rmad_Date_Delivery = Column(DateTime, nullable=True)
    rmad_DelioveryNote = Column(String(2000), nullable=True)

    # Flags
    rmad_isNewItem = Column(Boolean, nullable=True)
    rmad_IncludeInPotentialStock = Column(Boolean, nullable=True)
    rmad_isAvailable4DeliverySheet = Column(Boolean, nullable=True)

    # Import data
    impData_Custom_local = Column(String(255), nullable=True)
    impData_Number_local = Column(String(255), nullable=True)

    # Related
    rmad_relatedID = Column(BigInteger, nullable=True)
    bra_id_original = Column(Integer, nullable=True)

    # Warranty
    rmad_insertWarrantyDetail = Column(String(4000), nullable=True)
    rmad_insertWarrantyCertificates = Column(String(4000), nullable=True)

    # Delivery sheet / picking
    sds_id4Picking = Column(BigInteger, nullable=True)
    dsd_id4Picking = Column(BigInteger, nullable=True)
    sds_id4Delivery = Column(BigInteger, nullable=True)
    dsd_id4Delivery = Column(BigInteger, nullable=True)
    dl_id4Picking = Column(BigInteger, nullable=True)
    dl_id4delivery = Column(BigInteger, nullable=True)

    # Dates
    rmad_deliveryDate4Picking = Column(DateTime, nullable=True)
    rmad_deliveryDate4Delivery = Column(DateTime, nullable=True)
    rmad_Date_estimatedFinalization = Column(DateTime, nullable=True)
    rmad_handOverDate = Column(DateTime, nullable=True)
    rmad_handOver_user_id = Column(BigInteger, nullable=True)

    # GUID
    rmad_guid = Column(String(100), nullable=True)

    __table_args__ = (
        Index("idx_rmad_rmah_id", "rmah_id"),
        Index("idx_rmad_item_id", "item_id"),
        Index("idx_rmad_is_id", "is_id"),
        Index("idx_rmad_it_transaction", "it_transaction"),
        Index("idx_rmad_rmas_id", "rmas_id"),
        Index("idx_rmad_supp_id", "supp_id"),
        Index("idx_rmad_date_reception", "rmad_Date_Reception"),
        Index("idx_rmad_serial", "rmad_serial"),
    )

    def __repr__(self) -> str:
        return f"<TbRMADetail(rmad_id={self.rmad_id}, rmah_id={self.rmah_id}, item_id={self.item_id})>"
