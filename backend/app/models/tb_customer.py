"""
Modelo para tbCustomer - Clientes (versión reducida)
"""
from sqlalchemy import Column, Integer, String, Boolean, DateTime
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
    cust_name1 = Column(String(500))
    fc_id = Column(Integer)
    cust_taxNumber = Column(String(50), index=True)
    tnt_id = Column(Integer)

    # Dirección
    cust_address = Column(String(500))
    cust_city = Column(String(255))
    cust_zip = Column(String(20))
    country_id = Column(Integer)
    state_id = Column(Integer)

    # Contacto
    cust_phone1 = Column(String(100))
    cust_cellPhone = Column(String(100))
    cust_email = Column(String(255))

    # Comercial
    sm_id = Column(Integer)
    sm_id_2 = Column(Integer)
    cust_inactive = Column(Boolean, default=False)
    prli_id = Column(Integer)

    # MercadoLibre
    cust_MercadoLibreNickName = Column(String(255))
    cust_MercadoLibreID = Column(String(100))

    # Fechas de auditoría
    cust_cd = Column(DateTime)
    cust_LastUpdate = Column(DateTime)

    # Auditoría local
    created_at = Column(DateTime(timezone=True), server_default=func.now())
    updated_at = Column(DateTime(timezone=True), server_default=func.now(), onupdate=func.now())

    def __repr__(self):
        return f"<TBCustomer(cust_id={self.cust_id}, cust_name='{self.cust_name}', cust_taxNumber='{self.cust_taxNumber}')>"
