"""
Modelo para precio_gremio_override
Almacena precios de gremio editados manualmente que sobrescriben el cálculo automático
"""
from sqlalchemy import Column, Integer, Numeric, DateTime, ForeignKey, func
from sqlalchemy.orm import relationship
from app.core.database import Base


class PrecioGremioOverride(Base):
    __tablename__ = "precio_gremio_override"

    id = Column(Integer, primary_key=True, index=True)
    item_id = Column(Integer, unique=True, nullable=False, index=True)
    precio_gremio_sin_iva_manual = Column(Numeric(10, 2), nullable=False)
    precio_gremio_con_iva_manual = Column(Numeric(10, 2), nullable=False)
    created_at = Column(DateTime, server_default=func.now(), nullable=False)
    updated_at = Column(DateTime, server_default=func.now(), onupdate=func.now(), nullable=False)
    created_by_id = Column(Integer, ForeignKey('usuarios.id', ondelete='SET NULL'), nullable=True)
    updated_by_id = Column(Integer, ForeignKey('usuarios.id', ondelete='SET NULL'), nullable=True)

    # Relationships
    created_by = relationship("Usuario", foreign_keys=[created_by_id])
    updated_by = relationship("Usuario", foreign_keys=[updated_by_id])
