from sqlalchemy import Column, Integer, BigInteger, String, Numeric, DateTime, Boolean, Text, PrimaryKeyConstraint
from app.core.database import Base


class SaleOrderHeader(Base):
    """
    Modelo para tbSaleOrderHeader del ERP
    Cabecera de órdenes de venta
    """

    __tablename__ = "tb_sale_order_header"
    __table_args__ = (PrimaryKeyConstraint("comp_id", "bra_id", "soh_id"),)

    # Composite Primary Key
    comp_id = Column(Integer, nullable=False, index=True)
    bra_id = Column(Integer, nullable=False, index=True)
    soh_id = Column(BigInteger, nullable=False, index=True)

    # Campos principales (todos en minúsculas para PostgreSQL)
    soh_cd = Column(DateTime, index=True)
    soh_deliverydate = Column(DateTime)
    soh_observation1 = Column(Text)
    soh_observation2 = Column(Text)
    soh_observation3 = Column(Text)
    soh_observation4 = Column(Text)
    soh_quotation = Column(String(100))
    sm_id = Column(Integer)
    cust_id = Column(Integer, index=True)
    st_id = Column(Integer)
    disc_id = Column(Integer)
    dl_id = Column(Integer)
    cb_id = Column(Integer)
    soh_lastupdate = Column(DateTime)
    soh_limitdate = Column(DateTime)
    tt_id = Column(Integer)
    tt_class = Column(String(10))  # Puede ser 'A', 'B', etc
    soh_statusof = Column(Integer)
    user_id = Column(Integer)
    soh_isediting = Column(Boolean)
    soh_iseditingcd = Column(DateTime)
    df_id = Column(Integer)
    soh_total = Column(Numeric(18, 6))
    ssos_id = Column(Integer)
    soh_exchangetocustomercurrency = Column(Numeric(18, 6))
    chp_id = Column(Integer)
    soh_pl_df_id = Column(Integer)
    soh_customercurrency = Column(Integer)
    soh_withcollection = Column(Boolean)
    soh_withcollectionguid = Column(String(100))
    soh_discount = Column(Numeric(18, 6))
    soh_loan = Column(Numeric(18, 6))
    soh_packagesqty = Column(Integer)
    soh_internalannotation = Column(Text)
    curr_id4exchange = Column(Integer)
    curr_idexchange = Column(Integer)
    soh_atotal = Column(Numeric(18, 6))
    df_id4pl = Column(Integer)
    somp_id = Column(Integer)
    soh_feidnumber = Column(String(100))
    soh_incash = Column(Boolean)
    custf_id = Column(Integer)
    cust_id_guarantor = Column(Integer)
    ccp_id = Column(Integer)
    soh_mldeliverylabel = Column(String(255))
    soh_deliveryaddress = Column(Text)
    soh_mlquestionsandanswers = Column(Text)
    aux_3rdsales_lastcttransaction = Column(BigInteger)
    soh_mlid = Column(String(100))
    soh_mlguia = Column(String(100))
    pro_id = Column(Integer)
    aux_collectioninterest_lastcttransaction = Column(BigInteger)
    ws_cust_id = Column(Integer)
    ws_internalid = Column(String(100))
    ws_paymentgatewaystatusid = Column(String(100))
    ws_paymentgatewayreferenceid = Column(String(100))
    ws_ipfrom = Column(String(100))
    ws_st_id = Column(Integer)
    ws_dl_id = Column(Integer)
    soh_htmlnote = Column(Text)
    prli_id = Column(Integer, index=True)
    stor_id = Column(Integer)
    mlo_id = Column(BigInteger, index=True)
    mlshippingid = Column(BigInteger, index=True)
    soh_exchange2currency4total = Column(Numeric(18, 6))
    soh_currency4total = Column(Integer)
    soh_uniqueid = Column(String(100))
    soh_note4externaluse = Column(Text)
    soh_autoprocesslastorder = Column(Boolean)
    dc_id = Column(Integer)
    soh_isprintedfromsopreparation = Column(Boolean)
    soh_persistexchange = Column(Boolean)  # Es boolean, no numeric
    ct_transaction_precollection = Column(BigInteger)
    soh_isemailenvied = Column(Boolean)
    soh_deliverylabel = Column(String(255))
    ct_transaction_preinvoice = Column(BigInteger)

    # Campos personalizados para gestión de envíos
    codigo_envio_interno = Column(String(100), index=True)  # Para QR en etiquetas
    export_id = Column(Integer, index=True)  # ID de export del ERP (ej: 80 para pedidos pendientes)
    export_activo = Column(Boolean, default=True)  # True = activo en el export, False = archivado

    # Campos enriquecidos desde TiendaNube API
    tiendanube_number = Column(String(50), index=True)  # Número de orden TN (NRO-XXXXX)
    tiendanube_shipping_phone = Column(String(50))  # Teléfono del destinatario
    tiendanube_shipping_address = Column(Text)  # Dirección completa formateada
    tiendanube_shipping_city = Column(String(100))  # Ciudad/Barrio
    tiendanube_shipping_province = Column(String(100))  # Provincia
    tiendanube_shipping_zipcode = Column(String(20))  # Código postal
    tiendanube_recipient_name = Column(String(200))  # Nombre del destinatario

    # Campos de override manual de dirección de envío (prioridad para visualización)
    override_shipping_address = Column(Text)  # Dirección sobrescrita manualmente
    override_shipping_city = Column(String(255))  # Ciudad sobrescrita
    override_shipping_province = Column(String(255))  # Provincia sobrescrita
    override_shipping_zipcode = Column(String(20))  # Código postal sobrescrito
    override_shipping_phone = Column(String(100))  # Teléfono sobrescrito
    override_shipping_recipient = Column(String(255))  # Destinatario sobrescrito
    override_notes = Column(Text)  # Notas adicionales del override
    override_modified_by = Column(Integer)  # Usuario que modificó (user_id)
    override_modified_at = Column(DateTime)  # Fecha de modificación
    override_num_bultos = Column(Integer)  # Número de bultos para etiquetas
    override_tipo_domicilio = Column(String(50))  # Particular, Comercial, Sucursal

    def __repr__(self):
        return f"<SaleOrderHeader(soh_id={self.soh_id}, comp_id={self.comp_id}, mlo_id={self.mlo_id})>"
