from sqlalchemy import Column, Integer, BigInteger, String, Boolean, DateTime, Numeric, Text
from sqlalchemy.dialects.postgresql import UUID
from sqlalchemy.sql import func
from app.core.database import Base

class CommercialTransaction(Base):
    """
    Modelo para tbCommercialTransactions del ERP
    Contiene todas las transacciones comerciales (ventas, compras, remitos, etc.)
    """
    __tablename__ = "tb_commercial_transactions"

    # IDs principales
    comp_id = Column(Integer)
    bra_id = Column(Integer)
    ct_transaction = Column(BigInteger, primary_key=True, index=True)
    ct_pointOfSale = Column(Integer)
    ct_kindOf = Column(String(10), index=True)
    ct_docNumber = Column(String(50), index=True)

    # Fechas
    ct_date = Column(DateTime, index=True)
    ct_taxDate = Column(DateTime)
    ct_payDate = Column(DateTime)
    ct_deliveryDate = Column(DateTime)
    ct_processingDate = Column(DateTime)
    ct_lastPayDate = Column(DateTime)
    ct_cd = Column(DateTime)

    # Relaciones
    supp_id = Column(Integer)
    cust_id = Column(Integer, index=True)
    cust_id_related = Column(Integer)
    cust_id_guarantor = Column(Integer)
    custf_id = Column(Integer)
    ba_id = Column(Integer)
    cb_id = Column(Integer)
    user_id = Column(Integer)

    # Montos y totales
    ct_subtotal = Column(Numeric(18, 2))
    ct_total = Column(Numeric(18, 2))
    ct_discount = Column(Numeric(18, 2))
    ct_adjust = Column(Numeric(18, 2))
    ct_taxes = Column(Numeric(18, 2))
    ct_ATotal = Column(Numeric(18, 2))
    ct_ABalance = Column(Numeric(18, 2))
    ct_AAdjust = Column(Numeric(18, 2))
    ct_inCash = Column(Numeric(18, 2))
    ct_optionalValue = Column(Numeric(18, 2))
    ct_documentTotal = Column(Numeric(18, 2))

    # Monedas y tipos de cambio
    curr_id_transaction = Column(Integer)
    ct_ACurrency = Column(Integer)
    ct_ACurrencyExchange = Column(Numeric(18, 10))
    ct_CompanyCurrency = Column(Integer)
    ct_Branch2CompanyCurrencyExchange = Column(Numeric(18, 10))
    ct_dfExchange = Column(Numeric(18, 10))
    curr_id4Exchange = Column(Integer)
    ct_curr_IdExchange = Column(Numeric(18, 10))
    curr_id4dfExchange = Column(Integer)
    ct_dfExchangeOriginal = Column(Numeric(18, 10))
    ct_curr_IdExchangeOriginal = Column(Numeric(18, 10))

    # Referencias contables
    hacc_transaction = Column(Integer)
    sm_id = Column(Integer)
    disc_id = Column(Integer)
    df_id = Column(Integer)
    dl_id = Column(Integer)
    st_id = Column(Integer)
    sd_id = Column(Integer)
    puco_id = Column(Integer)

    # Ubicación
    country_id = Column(Integer)
    state_id = Column(Integer)

    # Estados y flags
    ct_Pending = Column(Boolean, default=True)
    ct_isAvailableForImport = Column(Boolean, default=False)
    ct_isAvailableForPayment = Column(Boolean, default=False)
    ct_isCancelled = Column(Boolean, default=False)
    ct_isSelected = Column(Boolean, default=False)
    ct_isMigrated = Column(Boolean, default=False)
    ct_powerBoardOK = Column(Boolean, default=False)
    ct_Fiscal_Check4EmptyNumbers = Column(Boolean, default=False)
    ct_DisableExchangeDifferenceInterest = Column(Boolean, default=False)

    # Ventas especiales / ecommerce
    ct_soh_bra_id = Column(Integer)
    ct_soh_id = Column(Integer)
    ct_transaction_PackingList = Column(String(100))
    ws_cust_Id = Column(Integer)
    ws_internalID = Column(String(100))
    ws_isLiquidated = Column(Boolean, default=False)
    ws_isLiquidatedCD = Column(Boolean, default=False)
    ws_is4Liquidation = Column(Boolean, default=False)
    ws_LiquidationNumber = Column(String(100))
    ws_st_id = Column(Integer)
    ws_dl_id = Column(Integer)

    # AFIP / Fiscales
    ct_CAI = Column(String(100))
    ct_CAIDate = Column(DateTime)
    ct_FEIdNumber = Column(String(100))

    # Descuentos detallados
    ct_Discount1 = Column(Numeric(18, 2), default=0)
    ct_Discount2 = Column(Numeric(18, 2), default=0)
    ct_Discount3 = Column(Numeric(18, 2), default=0)
    ct_Discount4 = Column(Numeric(18, 2), default=0)
    ct_discountPlanCoeficient = Column(Numeric(18, 10), default=1)

    # Paquetes y envíos
    ct_packagesQty = Column(Integer, default=0)
    ct_TransactionBarCode = Column(String(100))

    # Créditos
    ct_CreditIntPercentage = Column(Numeric(10, 4), default=0)
    ct_CreditIntPlusPercentage = Column(Numeric(10, 4), default=0)
    ctl_daysPastDue = Column(Integer, default=0)
    ccp_id = Column(Integer)

    # Otros IDs de referencia
    sctt_id = Column(Integer)
    suppa_id = Column(Integer)
    pt_id = Column(Integer)
    fc_id = Column(Integer)
    pro_id = Column(Integer)
    supp_id4CreditCardLiquidation = Column(Integer)
    def_id = Column(Integer)
    mlo_id = Column(Integer)
    dc_id = Column(Integer)

    # Campos de uso general (tags)
    ct_AllUseTag1 = Column(String(255))
    ct_AllUseTag2 = Column(String(255))
    ct_AllUseTag3 = Column(String(255))
    ct_AllUseTag4 = Column(String(255))

    # GUID y documentación
    ct_guid = Column(UUID(as_uuid=True), index=True)
    ct_transaction4ThirdSales = Column(String(100))
    ct_documentNumber = Column(String(100))
    ct_note = Column(Text)

    # Auditoría local
    created_at = Column(DateTime(timezone=True), server_default=func.now())
    updated_at = Column(DateTime(timezone=True), server_default=func.now(), onupdate=func.now())

    def __repr__(self):
        return f"<CommercialTransaction(ct_transaction={self.ct_transaction}, ct_kindOf={self.ct_kindOf}, ct_docNumber={self.ct_docNumber}, ct_total={self.ct_total})>"
