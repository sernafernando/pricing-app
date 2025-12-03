"""
Modelo para tbCustomer - Clientes
"""
from sqlalchemy import Column, Integer, String, Boolean, DateTime, Numeric, Text
from sqlalchemy.sql import func
from app.core.database import Base


class TBCustomer(Base):
    """Tabla de clientes del ERP"""
    __tablename__ = "tb_customer"

    # Primary Keys
    comp_id = Column(Integer, primary_key=True)
    cust_id = Column(Integer, primary_key=True, index=True)

    # Datos básicos
    bra_id = Column(Integer)
    cust_name = Column(String(500))
    cust_name1 = Column(String(500))  # Nombre alternativo/nickname
    fc_id = Column(Integer)  # Clase fiscal
    cust_taxNumber = Column(String(50), index=True)  # CUIT/DNI
    tnt_id = Column(Integer)  # Tipo de número de tax (CUIT, DNI, etc)

    # Ingresos Brutos
    stcIB_Id = Column(Integer)
    cust_taxIBNumber = Column(String(50))

    # Contacto
    cust_web = Column(String(255))
    cust_contact = Column(String(255))
    cust_phone1 = Column(String(100))
    cust_phone2 = Column(String(100))
    cust_cellPhone = Column(String(100))
    cust_cellPhone2 = Column(String(100))
    cust_email = Column(String(255))
    cust_fax = Column(String(100))
    cust_whatsapp = Column(String(100))

    # Dirección
    cust_address = Column(String(500))
    cust_city = Column(String(255))
    cust_zip = Column(String(20))
    country_id = Column(Integer)
    state_id = Column(Integer)
    city_id = Column(Integer)
    street_id = Column(Integer)
    cust_addressNumber = Column(String(50))
    cust_addressAdditional = Column(String(255))
    cust_addressFloor = Column(String(50))

    # Dirección de entrega
    cust_address4Delivery = Column(String(500))

    # Dirección de pagos
    cust_address4Payments = Column(String(500))

    # Estado
    cust_inactive = Column(Boolean, default=False)
    cust_isEditing = Column(Boolean, default=False)
    cust_isEditingCd = Column(DateTime)
    cust_isEditingUserId = Column(Integer)

    # Comercial
    sm_id = Column(Integer)  # Vendedor asignado
    sm_id_2 = Column(Integer)  # Vendedor secundario
    cust_partnerOf = Column(Integer)

    # Crédito
    cust_credit_max = Column(Numeric(18, 2))
    cust_credit_own = Column(Numeric(18, 2))
    cust_credit_Curr_Id = Column(Integer)
    curr_id = Column(Integer)

    # Configuraciones comerciales
    ck_id = Column(Integer)
    st_id = Column(Integer)
    disc_id = Column(Integer)
    dl_id = Column(Integer)
    prli_id = Column(Integer)  # Lista de precios
    prli_id_alternative = Column(Integer)
    stor_id = Column(Integer)
    coslis_id = Column(Integer)
    coslis_idB = Column(Integer)

    # Contabilidad
    acc_count_id = Column(Integer)

    # Usuarios
    user_id = Column(Integer)
    user_id4Insert = Column(Integer)
    user_id4LastUpdate = Column(Integer)

    # Web/eCommerce
    cust_webPassword = Column(String(255))
    cust_webNickName = Column(String(255))
    cust_webPending2Verify = Column(Boolean)
    cust_login = Column(String(255))
    cust_login_cd = Column(DateTime)
    cust_login_ip = Column(String(100))
    cust_login_name = Column(String(255))
    cust_showstock = Column(Boolean)
    cust_showpricelist = Column(Boolean)
    cust_showzerostockitems = Column(Boolean)

    # Orden de venta
    cust_SaleOrderMaxValue = Column(Numeric(18, 2))
    cust_SaleOrderDisableConcurrentProc = Column(Boolean)
    cust_SaleOrderBranchTransfer = Column(Boolean)
    bra_id4Emmition = Column(Integer)

    # Notas y anotaciones
    cust_annotation = Column(Text)
    cust_note1 = Column(Text)
    cust_note2 = Column(Text)
    cust_note3 = Column(Text)
    cust_note4 = Column(Text)
    cust_notes = Column(Text)
    cust_CRMComment = Column(Text)

    # Judicial
    cust_judMan = Column(Boolean)
    cust_judManBlockCollection = Column(Boolean)

    # Contactos adicionales
    cust_contact4Payments = Column(String(255))
    cust_email4Payments = Column(String(255))
    cust_contact4Management = Column(String(255))
    cust_email4Management = Column(String(255))
    cust_contact4Administration = Column(String(255))
    cust_email4Administration = Column(String(255))
    cust_contact4Logistics = Column(String(255))
    cust_email4Logistics = Column(String(255))
    cust_contact4Alternative = Column(String(255))
    cust_email4Alternative = Column(String(255))
    cust_contact4AlternativeII = Column(String(255))
    cust_email4AlternativeII = Column(String(255))
    cust_contact4RMA = Column(String(255))
    cust_email4RMA = Column(String(255))
    cust_address4RMA = Column(String(500))
    cust_phone4RMA = Column(String(100))
    cust_isAvailable4InternalRMA = Column(Boolean)

    # Actividad
    act_id = Column(Integer)

    # Exclusiones
    cust_excludeInCITI = Column(Boolean)
    cust_excludeOfCustomerMailing = Column(Boolean)
    cust_Mailing4CustOverdueDebt_Excluded = Column(Boolean)
    cust_disableNPS = Column(Boolean)

    # Rating
    rating_id = Column(Integer)
    rating_id_previous = Column(Integer)
    rating_id_cd = Column(DateTime)
    cust_ratingProcessCheck = Column(Boolean)

    # Datos personales
    cust_firstname = Column(String(255))
    cust_lastName = Column(String(255))
    cust_birthDay = Column(DateTime)
    cust_maleOrFemale = Column(String(10))
    cust_age = Column(Integer)
    marst_id = Column(Integer)  # Estado civil

    # Trabajo
    cust_jobTitle = Column(String(255))
    cust_jobAddress = Column(String(500))
    cust_jobCity = Column(String(255))
    cust_jobCity_Id = Column(Integer)
    cust_jobPhone = Column(String(100))
    cust_jobName = Column(String(255))
    cust_jobPayDate = Column(DateTime)
    cust_jobAdmissionDate = Column(DateTime)
    cust_jobYearInIt = Column(Integer)
    cust_jobPayIntervalIs15 = Column(Boolean)
    cust_remuneration = Column(Numeric(18, 2))

    # Propiedad
    cust_isOwner = Column(Boolean)
    cust_ownerOf = Column(String(255))

    # Corporación
    corp_id = Column(Integer)
    stg_id = Column(Integer)
    stca_id = Column(Integer)

    # Imagen
    cust_imageChecksum = Column(String(255))

    # Préstamos
    cust_disabled4PersonalLoan = Column(Boolean)
    cram_id = Column(Integer)
    cust_ramification = Column(String(255))
    rmap_id = Column(Integer)

    # MercadoLibre
    cust_MercadoLibreNickName = Column(String(255))
    cust_MercadoLibreID = Column(String(100))
    MLUser_Id = Column(Integer)

    # Verificación
    cust_checked = Column(Boolean)
    cust_4InitialValues = Column(Boolean)
    cust_updatedFromABM = Column(Boolean)

    # Factura electrónica
    fecountry_id = Column(Integer)
    fex_cuitID = Column(String(50))
    cust_ElectronicInvoice_MiPyme_Mode = Column(Integer)
    def_id = Column(Integer)
    cmde_noAction = Column(Boolean)

    # GBP específicos
    cust_GBPUrl = Column(String(500))
    cust_GBPModules = Column(String(255))
    cust_GBPDbName = Column(String(255))
    cust_GBPUserQty = Column(Integer)
    cust_GBPBranchQty = Column(Integer)
    cust_GBPCompanyQty = Column(Integer)
    cust_GBPLastURLUpdate = Column(DateTime)
    cust_GBPCG = Column(String(255))
    cust_GBPSN = Column(String(255))
    cust_GBPLPD = Column(DateTime)
    cust_GBPUrl2 = Column(String(500))
    cust_GBPUrl3 = Column(String(500))
    cust_GBPUrl4webSite = Column(String(500))
    cust_GBPDebtorInfo = Column(Text)
    cust_GBPMessage = Column(Text)
    cust_GBPImplementador = Column(String(255))
    cust_GBPCRM_user_id = Column(Integer)
    cust_GBPMeLi_serverURL = Column(String(500))
    cust_GBPComunityID = Column(String(100))
    cust_GBPCommunityURL = Column(String(500))
    cust_GBPInProduction = Column(Boolean)
    cust_hasCM05Configurations = Column(Boolean)

    # Migración
    cust_migrationID = Column(String(100))
    ws_internalID = Column(String(100))

    # Relaciones
    cust_id_related = Column(Integer)
    cust_4OnlySign = Column(Boolean)
    cust_credit_max_Last = Column(Numeric(18, 2))
    cust_credit_max_overComeDate = Column(DateTime)

    # Pagos
    cust_lastPaymentDatefromOtherERP = Column(DateTime)

    # Grupos
    brag_id = Column(Integer)
    ss_id = Column(Integer)

    # Otros
    sts_sujID = Column(Integer)
    cust_excludeFromSaleOrderCollect = Column(Boolean)
    col_TCR_1 = Column(String(255))
    col_GTA_1 = Column(String(255))

    # Fechas de auditoría
    cust_cd = Column(DateTime)  # Fecha creación
    cust_LastUpdate = Column(DateTime)  # Última actualización

    # Auditoría local
    created_at = Column(DateTime(timezone=True), server_default=func.now())
    updated_at = Column(DateTime(timezone=True), server_default=func.now(), onupdate=func.now())

    def __repr__(self):
        return f"<TBCustomer(cust_id={self.cust_id}, cust_name='{self.cust_name}', cust_taxNumber='{self.cust_taxNumber}')>"
