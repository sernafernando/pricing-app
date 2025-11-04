from sqlalchemy import Column, Integer, BigInteger, String, DateTime, Numeric, Text
from sqlalchemy.sql import func
from app.core.database import Base

class MercadoLibreOrderShipping(Base):
    """
    Modelo para tbMercadoLibre_ordersShipping del ERP
    Contiene información de envío de cada orden de MercadoLibre

    IMPORTANTE: Los nombres de columnas están en minúsculas en PostgreSQL
    """
    __tablename__ = "tb_mercadolibre_orders_shipping"

    # IDs principales
    comp_id = Column(Integer, index=True)
    mlm_id = Column(BigInteger, primary_key=True, index=True)
    mlo_id = Column(BigInteger, index=True)  # FK a tb_mercadolibre_orders_header
    mlshippingid = Column(String(50), index=True)

    # Información de envío
    mlshipment_type = Column(String(50))
    mlshipping_mode = Column(String(50))
    mlm_json = Column(Text)
    mlcost = Column(Numeric(18, 4))
    mllogistic_type = Column(String(50))
    mlstatus = Column(String(50), index=True)

    # Fechas de envío
    mlestimated_handling_limit = Column(DateTime, index=True)
    mlestimated_delivery_final = Column(DateTime)
    mlestimated_delivery_limit = Column(DateTime)
    ml_date_first_printed = Column(DateTime)
    ml_estimated_delivery_time_date = Column(DateTime)
    ml_estimated_delivery_time_shipping = Column(Integer)
    mlos_lastupdate = Column(DateTime)
    mlshippmentcolectadaytime = Column(DateTime)

    # Dirección de entrega
    mlreceiver_address = Column(Text)
    mlstreet_name = Column(String(500))
    mlstreet_number = Column(String(50))
    mlcomment = Column(Text)
    mlzip_code = Column(String(50))
    mlcity_name = Column(String(500))
    mlstate_name = Column(String(500))
    mlcity_id = Column(Text)  # Puede contener direcciones completas
    mlstate_id = Column(String(50))
    mlconuntry_name = Column(String(100))

    # Información del receptor
    mlreceiver_name = Column(String(500))
    mlreceiver_phone = Column(String(50))

    # Costos y fees
    mllist_cost = Column(Numeric(18, 4))
    ml_base_cost = Column(Numeric(18, 4))
    mlshippmentcost4buyer = Column(Numeric(18, 4))
    mlshippmentcost4seller = Column(Numeric(18, 4))
    mlshippmentgrossamount = Column(Numeric(18, 4))

    # Información adicional
    mldelivery_type = Column(String(50))
    mlshipping_method_id = Column(String(50))
    mltracking_number = Column(String(100))
    mlfulfilled = Column(String(50))
    mlcross_docking = Column(String(50))
    mlself_service = Column(String(50))
    ml_logistic_type = Column(String(50))
    ml_tracking_method = Column(String(255))
    mlturbo = Column(String(50))

    # Timestamps
    created_at = Column(DateTime, server_default=func.now())
    updated_at = Column(DateTime, server_default=func.now(), onupdate=func.now())
