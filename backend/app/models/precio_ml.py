from sqlalchemy import Column, Integer, String, Numeric, DateTime
from sqlalchemy.sql import func
from app.core.database import Base


class PrecioML(Base):
    __tablename__ = "precios_ml"

    id = Column(Integer, primary_key=True, index=True)
    item_id = Column(Integer, nullable=False, index=True)
    pricelist_id = Column(Integer, nullable=False, index=True)
    precio = Column(Numeric(15, 2))
    mla = Column(String(20), nullable=True, index=True)
    cotizacion_dolar = Column(Numeric(12, 2))
    fecha_actualizacion = Column(DateTime, default=func.now(), onupdate=func.now())
