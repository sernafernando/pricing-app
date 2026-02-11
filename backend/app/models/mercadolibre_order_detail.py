from sqlalchemy import Column, Integer, BigInteger, String, Boolean, DateTime, Numeric, Text
from sqlalchemy.sql import func
from app.core.database import Base


class MercadoLibreOrderDetail(Base):
    """
    Modelo para tbMercadoLibre_ordersDetail del ERP
    Contiene el detalle de productos/items de cada orden de MercadoLibre

    IMPORTANTE: Los nombres de columnas están en minúsculas en PostgreSQL
    """

    __tablename__ = "tb_mercadolibre_orders_detail"

    # IDs principales
    comp_id = Column(Integer, index=True)
    mlo_id = Column(BigInteger, index=True)  # FK a tb_mercadolibre_orders_header
    mlod_id = Column(BigInteger, primary_key=True, index=True)
    mlp_id = Column(BigInteger)
    item_id = Column(Integer, index=True)  # FK a productos

    # Precios y cantidades
    mlo_unit_price = Column(Numeric(18, 4))
    mlo_quantity = Column(Numeric(18, 4))
    mlo_currency_id = Column(String(10))

    # Fechas
    mlo_cd = Column(DateTime, index=True)
    mlod_lastupdate = Column(DateTime)

    # Información adicional
    mlo_note = Column(Text)
    mlo_is4availablestock = Column(Boolean, default=False)
    stor_id = Column(Integer)

    # Comisiones y fees
    mlo_listing_fee_amount = Column(Numeric(18, 4))
    mlo_sale_fee_amount = Column(Numeric(18, 4))

    # Descripción
    mlo_title = Column(String(500))
    mlvariationid = Column(String(50))

    # Timestamps
    created_at = Column(DateTime, server_default=func.now())
    updated_at = Column(DateTime, server_default=func.now(), onupdate=func.now())
