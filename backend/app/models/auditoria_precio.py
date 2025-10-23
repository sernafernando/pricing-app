from sqlalchemy import Column, Integer, String, Numeric, DateTime, ForeignKey
from sqlalchemy.orm import relationship
from datetime import datetime
from app.core.database import Base

class AuditoriaPrecio(Base):
    __tablename__ = "auditoria_precios"
    
    id = Column(Integer, primary_key=True, index=True)
    producto_id = Column(Integer, ForeignKey("productos_pricing.id"), nullable=False)
    usuario_id = Column(Integer, ForeignKey("usuarios.id"), nullable=False)
    
    # Precios anteriores
    precio_anterior = Column(Numeric(10, 2))
    precio_contado_anterior = Column(Numeric(10, 2))
    
    # Precios nuevos
    precio_nuevo = Column(Numeric(10, 2))
    precio_contado_nuevo = Column(Numeric(10, 2))
    
    # Metadata
    fecha_cambio = Column(DateTime, default=datetime.utcnow)
    comentario = Column(String(500), nullable=True)
    
    # Relaciones
    producto = relationship("ProductoPricing", back_populates="auditoria")
    usuario = relationship("Usuario")
