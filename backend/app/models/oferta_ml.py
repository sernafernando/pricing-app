from sqlalchemy import Column, Integer, String, Float, Date, ForeignKey, DateTime
from sqlalchemy.orm import relationship
from sqlalchemy.sql import func
from app.core.database import Base

class OfertaML(Base):
    __tablename__ = "ofertas_ml"
    
    id = Column(Integer, primary_key=True, index=True)
    mla = Column(String(50), ForeignKey('publicaciones_ml.mla'), index=True, nullable=False)
    
    fecha_desde = Column(Date, nullable=False)
    fecha_hasta = Column(Date, nullable=False)
    
    precio_final = Column(Float)
    aporte_meli_pesos = Column(Float)
    aporte_meli_porcentaje = Column(Float)
    
    fecha_sync = Column(DateTime(timezone=True), server_default=func.now())
    updated_at = Column(DateTime(timezone=True), onupdate=func.now())
    
    # Relación
    publicacion = relationship("PublicacionML")
