from sqlalchemy import Column, Integer, BigInteger, String, Boolean, DateTime, Numeric, Text
from sqlalchemy.dialects.postgresql import UUID
from sqlalchemy.sql import func
from app.core.database import Base


class CommercialTransaction(Base):
    """
    Modelo para tbCommercialTransactions del ERP
    Contiene todas las transacciones comerciales (ventas, compras, remitos, etc.)

    IMPORTANTE: Los nombres de atributos mantienen camelCase para compatibilidad con el código,
    pero se mapean a nombres en minúsculas en PostgreSQL usando el parámetro 'name'
    """

    __tablename__ = "tb_commercial_transactions"

    # IDs principales
    comp_id = Column(Integer)
    bra_id = Column(Integer)
    ct_transaction = Column(BigInteger, primary_key=True, index=True)
    ct_pointOfSale = Column("ct_pointofsale", Integer)
    ct_kindOf = Column("ct_kindof", String(10), index=True)
    ct_docNumber = Column("ct_docnumber", String(50), index=True)

    # Fechas
    ct_date = Column(DateTime, index=True)
    ct_taxDate = Column("ct_taxdate", DateTime)
    ct_payDate = Column("ct_paydate", DateTime)
    ct_deliveryDate = Column("ct_deliverydate", DateTime)
    ct_processingDate = Column("ct_processingdate", DateTime)
    ct_lastPayDate = Column("ct_lastpaydate", DateTime)
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
    ct_ATotal = Column("ct_atotal", Numeric(18, 2))
    ct_ABalance = Column("ct_abalance", Numeric(18, 2))
    ct_AAdjust = Column("ct_aadjust", Numeric(18, 2))
    ct_inCash = Column("ct_incash", Numeric(18, 2))
    ct_optionalValue = Column("ct_optionalvalue", Numeric(18, 2))
    ct_documentTotal = Column("ct_documenttotal", Numeric(18, 2))

    # Monedas y tipos de cambio
    curr_id_transaction = Column(Integer)
    ct_ACurrency = Column("ct_acurrency", Integer)
    ct_ACurrencyExchange = Column("ct_acurrencyexchange", Numeric(18, 10))
    ct_CompanyCurrency = Column("ct_companycurrency", Integer)
    ct_Branch2CompanyCurrencyExchange = Column("ct_branch2companycurrencyexchange", Numeric(18, 10))
    ct_dfExchange = Column("ct_dfexchange", Numeric(18, 10))
    curr_id4Exchange = Column("curr_id4exchange", Integer)
    ct_curr_IdExchange = Column("ct_curr_idexchange", Numeric(18, 10))
    curr_id4dfExchange = Column("curr_id4dfexchange", Integer)
    ct_dfExchangeOriginal = Column("ct_dfexchangeoriginal", Numeric(18, 10))
    ct_curr_IdExchangeOriginal = Column("ct_curr_idexchangeoriginal", Numeric(18, 10))

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
    ct_Pending = Column("ct_pending", Boolean, default=True)
    ct_isAvailableForImport = Column("ct_isavailableforimport", Boolean, default=False)
    ct_isAvailableForPayment = Column("ct_isavailableforpayment", Boolean, default=False)
    ct_isCancelled = Column("ct_iscancelled", Boolean, default=False)
    ct_isSelected = Column("ct_isselected", Boolean, default=False)
    ct_isMigrated = Column("ct_ismigrated", Boolean, default=False)
    ct_powerBoardOK = Column("ct_powerboardok", Boolean, default=False)
    ct_Fiscal_Check4EmptyNumbers = Column("ct_fiscal_check4emptynumbers", Boolean, default=False)
    ct_DisableExchangeDifferenceInterest = Column("ct_disableexchangedifferenceinterest", Boolean, default=False)

    # Ventas especiales / ecommerce
    ct_soh_bra_id = Column(Integer)
    ct_soh_id = Column(Integer)
    ct_transaction_PackingList = Column("ct_transaction_packinglist", String(100))
    ws_cust_Id = Column("ws_cust_id", Integer)
    ws_internalID = Column("ws_internalid", String(100))
    ws_isLiquidated = Column("ws_isliquidated", Boolean, default=False)
    ws_isLiquidatedCD = Column("ws_isliquidatedcd", Boolean, default=False)
    ws_is4Liquidation = Column("ws_is4liquidation", Boolean, default=False)
    ws_LiquidationNumber = Column("ws_liquidationnumber", String(100))
    ws_st_id = Column(Integer)
    ws_dl_id = Column(Integer)

    # AFIP / Fiscales
    ct_CAI = Column("ct_cai", String(100))
    ct_CAIDate = Column("ct_caidate", DateTime)
    ct_FEIdNumber = Column("ct_feidnumber", String(100))

    # Descuentos detallados
    ct_Discount1 = Column("ct_discount1", Numeric(18, 2), default=0)
    ct_Discount2 = Column("ct_discount2", Numeric(18, 2), default=0)
    ct_Discount3 = Column("ct_discount3", Numeric(18, 2), default=0)
    ct_Discount4 = Column("ct_discount4", Numeric(18, 2), default=0)
    ct_discountPlanCoeficient = Column("ct_discountplancoeficient", Numeric(18, 10), default=1)

    # Paquetes y envíos
    ct_packagesQty = Column("ct_packagesqty", Integer, default=0)
    ct_TransactionBarCode = Column("ct_transactionbarcode", String(100))

    # Créditos
    ct_CreditIntPercentage = Column("ct_creditintpercentage", Numeric(10, 4), default=0)
    ct_CreditIntPlusPercentage = Column("ct_creditintpluspercentage", Numeric(10, 4), default=0)
    ctl_daysPastDue = Column("ctl_dayspastdue", Integer, default=0)
    ccp_id = Column(Integer)

    # Otros IDs de referencia
    sctt_id = Column(Integer)
    suppa_id = Column(Integer)
    pt_id = Column(Integer)
    fc_id = Column(Integer)
    pro_id = Column(Integer)
    supp_id4CreditCardLiquidation = Column("supp_id4creditcardliquidation", Integer)
    def_id = Column(Integer)
    mlo_id = Column(Integer)
    dc_id = Column(Integer)

    # Campos de uso general (tags)
    ct_AllUseTag1 = Column("ct_allusetag1", String(255))
    ct_AllUseTag2 = Column("ct_allusetag2", String(255))
    ct_AllUseTag3 = Column("ct_allusetag3", String(255))
    ct_AllUseTag4 = Column("ct_allusetag4", String(255))

    # GUID y documentación
    ct_guid = Column(UUID(as_uuid=True), index=True)
    ct_transaction4ThirdSales = Column("ct_transaction4thirdsales", String(100))
    ct_documentNumber = Column("ct_documentnumber", String(100))
    ct_note = Column(Text)

    # Auditoría local
    created_at = Column(DateTime(timezone=True), server_default=func.now())
    updated_at = Column(DateTime(timezone=True), server_default=func.now(), onupdate=func.now())

    def __repr__(self):
        return f"<CommercialTransaction(ct_transaction={self.ct_transaction}, ct_kindOf={self.ct_kindOf}, ct_docNumber={self.ct_docNumber}, ct_total={self.ct_total})>"
