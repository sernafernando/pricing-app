from sqlalchemy import Column, Integer, String, Float, Boolean, DateTime, Enum as SQLEnum, ForeignKey
from sqlalchemy.orm import relationship
from sqlalchemy.sql import func
from app.core.database import Base
import enum

class TipoMoneda(str, enum.Enum):
    ARS = "ARS"
    USD = "USD"

class ProductoERP(Base):
    __tablename__ = "productos_erp"
    
    item_id = Column(Integer, primary_key=True, index=True)
    codigo = Column(String(100), index=True)
    descripcion = Column(String(500), index=True)
    marca = Column(String(100), index=True)
    categoria = Column(String(100))
    subcategoria_id = Column(Integer)
    
    costo = Column(Float)
    moneda_costo = Column(SQLEnum(TipoMoneda), default=TipoMoneda.ARS)
    iva = Column(Float, default=21.0)
    envio = Column(Float, default=0.0)
    
    stock = Column(Integer, default=0)
    activo = Column(Boolean, default=True)
    
    fecha_sync = Column(DateTime(timezone=True), server_default=func.now())
    updated_at = Column(DateTime(timezone=True), onupdate=func.now())
    
    # Relaciones
    pricing = relationship("ProductoPricing", back_populates="producto", uselist=False)
    publicaciones_ml = relationship("PublicacionML", back_populates="producto")

class ProductoPricing(Base):
    __tablename__ = "productos_pricing"
    
    id = Column(Integer, primary_key=True, index=True)
    item_id = Column(Integer, ForeignKey('productos_erp.item_id'), index=True, unique=True)
    
    precio_lista_ml = Column(Float)
    markup_calculado = Column(Float)
    usuario_id = Column(Integer, ForeignKey('usuarios.id'))
    motivo_cambio = Column(String(255))
    
    fecha_modificacion = Column(DateTime(timezone=True), server_default=func.now())
    
    producto = relationship("ProductoERP", back_populates="pricing")
    usuario = relationship("Usuario", back_populates="precios_modificados")
    historial = relationship("HistorialPrecio", back_populates="producto_pricing")

class HistorialPrecio(Base):
    __tablename__ = "historial_precios"
    
    id = Column(Integer, primary_key=True, index=True)
    producto_pricing_id = Column(Integer, ForeignKey('productos_pricing.id'), index=True)
    
    precio_anterior = Column(Float)
    precio_nuevo = Column(Float)
    
    usuario_id = Column(Integer, ForeignKey('usuarios.id'))
    motivo = Column(String(255))
    timestamp = Column(DateTime(timezone=True), server_default=func.now())
    
    producto_pricing = relationship("ProductoPricing", back_populates="historial")
