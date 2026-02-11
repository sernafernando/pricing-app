from sqlalchemy import Column, Integer, BigInteger, String, Boolean, DateTime, Numeric, Text
from sqlalchemy.dialects.postgresql import UUID
from sqlalchemy.sql import func
from app.core.database import Base


class ItemTransaction(Base):
    """
    Modelo para tbItemTransactions del ERP
    Contiene el detalle de cada ítem/producto en cada transacción comercial

    IMPORTANTE: Los nombres de columnas están en minúsculas en PostgreSQL
    """

    __tablename__ = "tb_item_transactions"

    # IDs principales
    comp_id = Column(Integer)
    bra_id = Column(Integer)
    ct_transaction = Column(BigInteger, index=True)
    it_transaction = Column(BigInteger, primary_key=True, index=True)
    item_id = Column(Integer, index=True)

    # Cantidades y precios básicos
    it_qty = Column(Numeric(18, 4))
    it_pricewithoothers = Column(Numeric(18, 4))
    it_price = Column(Numeric(18, 4))
    curr_id = Column(Integer)
    it_exchangetobranchcurrency = Column(Numeric(18, 10))

    # Precios de costo
    it_priceofcost = Column(Numeric(18, 4))
    it_priceofcostpp = Column(Numeric(18, 4))
    it_priceofcostlastpurchase = Column(Numeric(18, 4))
    it_pricebofcost = Column(Numeric(18, 4))
    it_pricebofcostpp = Column(Numeric(18, 4))
    it_pricebofcostlastpurchase = Column(Numeric(18, 4))

    # Precios originales
    it_originalprice = Column(Numeric(18, 4))
    it_originalpricecurrency = Column(Integer)
    it_exchangetooriginalpricecurrency = Column(Numeric(18, 10))

    # Storage y locación
    stor_id = Column(Integer)
    it_storeprevious = Column(Integer)
    prli_id = Column(Integer)
    byor_id = Column(Integer)

    # Flags de tipo
    it_isproduction = Column(Boolean, default=False)
    it_isassociation = Column(Boolean, default=False)
    it_isassociationgroup = Column(Boolean, default=False)

    # Fechas y orden
    it_cd = Column(DateTime, index=True)
    it_packinginvoicepend = Column(Numeric(18, 4))
    it_order = Column(Integer)
    so_id = Column(Integer)

    # Garantías y descuentos
    it_guarantee = Column(Integer)
    it_itemdiscounttotal = Column(Numeric(18, 4))
    it_totaldiscounttotal = Column(Numeric(18, 4))
    it_creditint = Column(Numeric(18, 4))
    it_creditintplus = Column(Numeric(18, 4))

    # Referencias contables
    puco_id = Column(Integer)
    it_poh_bra_id = Column(Integer)
    it_poh_id = Column(Integer)
    it_soh_id = Column(Integer)
    it_sod_id = Column(Integer)

    # RMA
    rmah_id = Column(Integer)
    rmad_id = Column(Integer)
    it_qty_rma = Column(Numeric(18, 4))
    it_tis_id_aux = Column(Integer)

    # Notas
    it_note1 = Column(Text)
    it_note2 = Column(Text)

    # Packing invoice
    it_packinginvoiceselected = Column(Numeric(18, 4))
    it_cancelled = Column(Boolean, default=False)
    it_priceb = Column(Numeric(18, 4))
    it_ismade = Column(Boolean, default=False)

    # Referencias de origen
    it_item_id_origin = Column(Integer)
    tmp_tis_id = Column(Integer)
    it_packinginvoicependoriginal = Column(Numeric(18, 4))
    it_packinginvoiceselectedguid = Column(UUID(as_uuid=True))
    it_transaction_original = Column(BigInteger)
    it_transaction_nostockdiscount = Column(BigInteger)

    # Moneda de ventas
    it_salescurrid4exchangetobranchcurrency = Column(Integer)

    # Tags de uso general
    it_allusetag1 = Column(String(255))
    it_allusetag2 = Column(String(255))
    it_allusetag3 = Column(String(255))
    it_allusetag4 = Column(String(255))

    # Descuentos detallados
    it_discount1 = Column(Numeric(18, 4), default=0)
    it_discount2 = Column(Numeric(18, 4), default=0)
    it_discount3 = Column(Numeric(18, 4), default=0)
    it_discount4 = Column(Numeric(18, 4), default=0)

    # Listas de costos
    coslis_id = Column(Integer)
    coslis_idb = Column(Integer)
    supp_id = Column(Integer)
    camp_id = Column(Integer)

    # Transacciones relacionadas
    it_transaction_originalew = Column(BigInteger)

    # Flags de transferencia y ajustes
    it_isinternaltransfer = Column(Boolean, default=False)
    it_isrmasuppliercreditnote = Column(Boolean, default=False)
    it_isfaststockadjustment = Column(Boolean, default=False)
    it_isstockadjustment = Column(Boolean, default=False)
    it_isstockcontrol = Column(Boolean, default=False)

    # Stock y préstamos
    sdlmt_id = Column(Integer)
    sreas_id = Column(Integer)
    it_loannumberofpays = Column(Integer)
    sitt_id = Column(Integer)
    it_deliverydate = Column(DateTime)
    itstkpld_id = Column(Integer)
    it_nostockcheck = Column(Boolean, default=False)

    # Más transacciones relacionadas
    it_transaction_originaldiv = Column(BigInteger)

    # Recargos
    it_surcharge1 = Column(Numeric(18, 4), default=0)
    it_surcharge2 = Column(Numeric(18, 4), default=0)
    it_surcharge3 = Column(Numeric(18, 4), default=0)
    it_surcharge4 = Column(Numeric(18, 4), default=0)

    # Transferencias entre sucursales
    stor_id_related4branchtransfer = Column(Integer)
    it_transaction_related4branchtransfer = Column(BigInteger)

    # Purchase order
    it_pod_id = Column(Integer)
    pubh_id = Column(Integer)

    # eCommerce y seguros
    it_ewaddress = Column(Text)
    it_insurancedays = Column(Integer)
    insud_id = Column(Integer)
    insud_certificatenumber = Column(String(100))

    # Pricing
    it_priceofprli_id4creditincash = Column(Numeric(18, 4))

    # PC Config
    it_ispcconfig = Column(Boolean, default=False)
    it_isblocked4delivery = Column(Boolean, default=False)
    it_isfrompconfigctrlid = Column(Integer)
    item_idfrompreinvoice = Column(Integer)

    # MercadoLibre costs
    it_mlcost = Column(Numeric(18, 4))
    it_iscompensed = Column(Boolean, default=False)

    # Web shop pricing
    ws_price = Column(Numeric(18, 4))
    ws_curr_id = Column(Integer)
    mlo_id = Column(Integer)

    # Delivery y costos adicionales
    it_deliverycharge = Column(Numeric(18, 4))
    it_mpcost = Column(Numeric(18, 4))
    it_mecost = Column(Numeric(18, 4))

    # Cancelación de packing invoice
    it_packinginvoicependcancell_user_id = Column(Integer)
    it_packinginvoicependcancell_cd = Column(DateTime)

    # Emisión y facturación
    it_disableprintinemission = Column(Boolean, default=False)
    it_packinginvoiceqtyinvoiced = Column(Numeric(18, 4))

    # Cupón web shop
    wscup_id = Column(Integer)

    # Branch transfer
    it_isinbranchtransfertotalizerstorage = Column(Boolean, default=False)

    # Descuento de plan
    tis_itemdiscountplan = Column(Numeric(18, 4))
    it_itemdiscount = Column(Numeric(18, 4))

    # Auditoría local
    created_at = Column(DateTime(timezone=True), server_default=func.now())
    updated_at = Column(DateTime(timezone=True), server_default=func.now(), onupdate=func.now())

    def __repr__(self):
        return f"<ItemTransaction(it_transaction={self.it_transaction}, ct_transaction={self.ct_transaction}, item_id={self.item_id}, it_qty={self.it_qty})>"
