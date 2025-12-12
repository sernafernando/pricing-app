"""
Modelo para tbBranch - Sucursales (versión reducida)
"""
from sqlalchemy import Column, Integer, String, Boolean, DateTime
from sqlalchemy.sql import func
from app.core.database import Base


class TBBranch(Base):
    """Tabla de sucursales del ERP"""
    __tablename__ = "tb_branch"

    # Primary Keys
    comp_id = Column(Integer, primary_key=True)
    bra_id = Column(Integer, primary_key=True, index=True)

    # Datos básicos
    bra_desc = Column(String(255))
    bra_maindesc = Column(String(255))
    country_id = Column(Integer)
    state_id = Column(Integer)

    # Dirección
    bra_address = Column(String(500))
    bra_phone = Column(String(100))
    bra_taxnumber = Column(String(50))

    # Estado
    bra_disabled = Column(Boolean, default=False)

    # Auditoría local
    created_at = Column(DateTime(timezone=True), server_default=func.now())
    updated_at = Column(DateTime(timezone=True), server_default=func.now(), onupdate=func.now())

    def __repr__(self):
        return f"<TBBranch(bra_id={self.bra_id}, bra_desc='{self.bra_desc}')>"
