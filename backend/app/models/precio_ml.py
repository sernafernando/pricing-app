from sqlalchemy import Column, Integer, String, Numeric, DateTime
from sqlalchemy.sql import func
from app.core.database import Base

class PrecioML(Base):
    __tablename__ = "precios_ml"
    
    id = Column(Integer, primary_key=True, index=True)
    mla = Column(String(20), nullable=False, index=True)
    pricelist_id = Column(Integer, nullable=False, index=True)
    precio = Column(Numeric(10, 2))
    fecha_actualizacion = Column(DateTime, default=func.now(), onupdate=func.now())
