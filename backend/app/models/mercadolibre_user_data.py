from sqlalchemy import Column, BigInteger, String, DateTime
from sqlalchemy.sql import func
from app.core.database import Base


class MercadoLibreUserData(Base):
    """
    Modelo para tbMercadoLibre_UsersData del ERP.
    Contiene datos del comprador (buyer) de MercadoLibre: nickname, dirección, billing, etc.

    JOIN path para obtener nickname en etiquetas:
    etiquetas_envio.shipping_id
      → tb_mercadolibre_orders_shipping.mlshippingid (via mlo_id)
      → tb_mercadolibre_orders_header.mlo_id
      → header.mluser_id
      → tb_mercadolibre_users_data.mluser_id
      → nickname
    """

    __tablename__ = "tb_mercadolibre_users_data"

    # PK
    mluser_id = Column(BigInteger, primary_key=True, index=True)

    # Datos del usuario
    nickname = Column(String(255), index=True)
    identification_type = Column(String(255))
    identification_number = Column(String(255))

    # Dirección principal
    address = Column(String(500))
    citi = Column(String(255))
    zip_code = Column(String(50))
    state = Column(String(255))

    # Contacto
    phone = Column(String(255))
    alternative_phone = Column(String(255))
    secure_email = Column(String(255))
    email = Column(String(255))

    # Receptor
    receiver_name = Column(String(255))
    receiver_phone = Column(String(255))

    # Código interno
    mlu_cd = Column(String(255))

    # Datos de facturación (billing)
    billing_state_name = Column(String(255))
    billing_doc_number = Column(String(255))
    billing_street_name = Column(String(500))
    billing_city_name = Column(String(255))
    billing_zip_code = Column(String(50))
    billing_street_number = Column(String(255))
    billing_doc_type = Column(String(255))
    billing_first_name = Column(String(255))
    billing_last_name = Column(String(255))
    billing_site_id = Column(String(50))

    # Timestamps
    created_at = Column(DateTime, server_default=func.now())
    updated_at = Column(DateTime, server_default=func.now(), onupdate=func.now())
