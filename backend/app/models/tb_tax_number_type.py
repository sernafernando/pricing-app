"""
Modelo para tbsysTaxNumberTypes - Tipos de Número de Impuesto (versión reducida)
"""
from sqlalchemy import Column, Integer, String, DateTime
from sqlalchemy.sql import func
from app.core.database import Base


class TBTaxNumberType(Base):
    """Tabla de tipos de número de impuesto del ERP"""
    __tablename__ = "tb_tax_number_type"

    # Primary Key
    tnt_id = Column(Integer, primary_key=True, index=True)

    # Datos básicos
    tnt_desc = Column(String(255))
    tnt_afip = Column(Integer)

    # Auditoría local
    created_at = Column(DateTime(timezone=True), server_default=func.now())
    updated_at = Column(DateTime(timezone=True), server_default=func.now(), onupdate=func.now())

    def __repr__(self):
        return f"<TBTaxNumberType(tnt_id={self.tnt_id}, tnt_desc='{self.tnt_desc}')>"
