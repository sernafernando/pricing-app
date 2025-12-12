"""
Modelo para tbsysFiscalClass - Clases Fiscales (versión reducida)
"""
from sqlalchemy import Column, Integer, String, DateTime
from sqlalchemy.sql import func
from app.core.database import Base


class TBFiscalClass(Base):
    """Tabla de clases fiscales del ERP"""
    __tablename__ = "tb_fiscal_class"

    # Primary Key
    fc_id = Column(Integer, primary_key=True, index=True)

    # Datos básicos
    fc_desc = Column(String(255))
    fc_kindof = Column(String(10))
    country_id = Column(Integer)
    fc_legaltaxid = Column(Integer)

    # Auditoría local
    created_at = Column(DateTime(timezone=True), server_default=func.now())
    updated_at = Column(DateTime(timezone=True), server_default=func.now(), onupdate=func.now())

    def __repr__(self):
        return f"<TBFiscalClass(fc_id={self.fc_id}, fc_desc='{self.fc_desc}')>"
