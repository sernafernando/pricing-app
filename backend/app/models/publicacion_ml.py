from sqlalchemy import Column, Integer, String, ForeignKey, DateTime, Index
from sqlalchemy.orm import relationship
from sqlalchemy.sql import func
from app.core.database import Base

class PublicacionML(Base):
    __tablename__ = "publicaciones_ml"
    
    id = Column(Integer, primary_key=True, index=True)
    mla = Column(String(50), unique=True, index=True, nullable=False)
    item_id = Column(Integer, ForeignKey('productos_erp.item_id'), nullable=False)
    codigo = Column(String(100))
    item_title = Column(String(500))
    pricelist_id = Column(Integer)
    lista_nombre = Column(String(100))
    
    fecha_sync = Column(DateTime(timezone=True), server_default=func.now())
    updated_at = Column(DateTime(timezone=True), onupdate=func.now())
    
    producto = relationship("ProductoERP", back_populates="publicaciones_ml")
    
    __table_args__ = (
        Index('ix_publicaciones_item_pricelist', 'item_id', 'pricelist_id'),
    )
