"""
Modelo para tbsysState - Estados/Provincias
"""
from sqlalchemy import Column, Integer, String, DateTime
from sqlalchemy.sql import func
from app.core.database import Base


class TBState(Base):
    """Tabla de estados/provincias del ERP"""
    __tablename__ = "tb_state"

    # Primary Keys
    country_id = Column(Integer, primary_key=True)
    state_id = Column(Integer, primary_key=True, index=True)

    # Datos básicos
    state_desc = Column(String(255))
    state_afip = Column(Integer)
    state_jurisdiccion = Column(Integer)
    state_arba_cot = Column(String(10))
    state_visatodopago = Column(String(50))
    country_visatodopago = Column(String(50))
    mlstatedescription = Column(String(255))
    state_enviopackid = Column(String(50))

    # Auditoría local
    created_at = Column(DateTime(timezone=True), server_default=func.now())
    updated_at = Column(DateTime(timezone=True), server_default=func.now(), onupdate=func.now())

    def __repr__(self):
        return f"<TBState(country_id={self.country_id}, state_id={self.state_id}, state_desc='{self.state_desc}')>"
