"""
Modelo para tbSalesman - Vendedores (versión reducida)
"""

from sqlalchemy import Column, Integer, String, Boolean, DateTime, Numeric
from sqlalchemy.sql import func
from app.core.database import Base


class TBSalesman(Base):
    """Tabla de vendedores del ERP"""

    __tablename__ = "tb_salesman"

    # Primary Keys
    comp_id = Column(Integer, primary_key=True)
    sm_id = Column(Integer, primary_key=True, index=True)

    # Datos básicos
    sm_name = Column(String(255))
    sm_email = Column(String(255))
    bra_id = Column(Integer)

    # Comisiones
    sm_commission_bysale = Column(Numeric(10, 4))
    sm_commission_byreceive = Column(Numeric(10, 4))

    # Estado
    sm_disabled = Column(Boolean, default=False)

    # Auditoría local
    created_at = Column(DateTime(timezone=True), server_default=func.now())
    updated_at = Column(DateTime(timezone=True), server_default=func.now(), onupdate=func.now())

    def __repr__(self):
        return f"<TBSalesman(sm_id={self.sm_id}, sm_name='{self.sm_name}')>"
