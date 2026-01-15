from sqlalchemy import Column, Integer, BigInteger, String, Boolean, DateTime, Numeric, JSON
from sqlalchemy.sql import func
from app.core.database import Base

class MercadoLibreOrderHeader(Base):
    """
    Modelo para tbMercadoLibre_ordersHeader del ERP
    Contiene las órdenes de MercadoLibre

    IMPORTANTE: Los nombres de columnas están en minúsculas en PostgreSQL
    """
    __tablename__ = "tb_mercadolibre_orders_header"

    # IDs principales
    comp_id = Column(Integer, index=True)
    mlo_id = Column(BigInteger, primary_key=True, index=True)
    mluser_id = Column(BigInteger)
    cust_id = Column(Integer, index=True)
    prli_id = Column(Integer, index=True)  # Price List ID histórico de la venta

    # JSONs
    mlo_firstjson = Column(JSON)
    mlo_lastjson = Column(JSON)

    # IDs de MercadoLibre (VARCHAR porque pueden ser muy grandes o tener formato especial)
    ml_id = Column(String(50), index=True)
    mlorder_id = Column(String(50), index=True)
    mlshippingid = Column(String(50))
    mlpickupid = Column(String(50))
    ml_pack_id = Column(String(50))

    # Fechas
    ml_date_created = Column(DateTime, index=True)
    ml_date_closed = Column(DateTime)
    ml_last_updated = Column(DateTime)
    mlo_cd = Column(DateTime)

    # Montos
    mlo_shippingcost = Column(Numeric(18, 2))
    mlo_transaction_amount = Column(Numeric(18, 2))
    mlo_cupon_amount = Column(Numeric(18, 2))
    mlo_overpaid_amount = Column(Numeric(18, 2))
    mlo_total_paid_amount = Column(Numeric(18, 2))

    # Estado y referencias
    mlo_status = Column(String(255), index=True)
    mlpickupperson = Column(String(255))
    mlbra_id = Column(Integer)
    mls_id = Column(Integer)

    # Información del usuario/cliente
    mlo_email = Column(String(255))
    identificationnumber = Column(BigInteger)
    identificationtype = Column(String(255))

    # Información de MercadoLibre User
    mluser_identificationtype = Column(String(255))
    mluser_identificationnumber = Column(BigInteger)
    mluser_address = Column(String(255))
    mluser_state = Column(String(255))
    mluser_citi = Column(String(255))
    mluser_zip_code = Column(String(255))
    mluser_phone = Column(String(255))
    mluser_email = Column(String(255))
    mluser_receiver_name = Column(String(255))
    mluser_receiver_phone = Column(String(255))
    mluser_alternative_phone = Column(String(255))
    mluser_first_name = Column(String(255))
    mluser_last_name = Column(String(255))

    # Banderas booleanas
    mlo_issaleordergenerated = Column(Boolean, default=False)
    mlo_ispaid = Column(Boolean, default=False)
    mlo_isdelivered = Column(Boolean, default=False)
    mlo_islabelprinted = Column(Boolean, default=False)
    mlo_isqualified = Column(Boolean, default=False)
    mlo_issaleorderemmited = Column(Boolean, default=False)
    mlo_iscollected = Column(Boolean, default=False)
    mlo_iswithfraud = Column(Boolean, default=False)
    mlo_isorderreceiptmessage = Column(Boolean, default=False)
    mlo_iscancelled = Column(Boolean, default=False)
    mlo_ismshops = Column(Boolean, default=False)
    mlo_mustprintlabel = Column(Boolean, default=False)
    mlo_ismshops_invited = Column(Boolean, default=False)
    mlo_orderswithdiscountcouponincludeinpricev2 = Column(Boolean, default=False)

    # Envío y tracking
    mlo_me1_deliverystatus = Column(String(255))
    mlo_me1_deliverytracking = Column(String(255))

    # Timestamps
    created_at = Column(DateTime, server_default=func.now())
    updated_at = Column(DateTime, server_default=func.now(), onupdate=func.now())
