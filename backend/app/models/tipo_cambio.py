from sqlalchemy import Column, Integer, String, Float, Date, DateTime
from sqlalchemy.sql import func
from app.core.database import Base


class TipoCambio(Base):
    __tablename__ = "tipo_cambio"

    id = Column(Integer, primary_key=True, index=True)
    fecha = Column(Date, index=True)
    moneda = Column(String(10), index=True)
    compra = Column(Float)
    venta = Column(Float)
    timestamp_actualizacion = Column(DateTime(timezone=True), server_default=func.now())
