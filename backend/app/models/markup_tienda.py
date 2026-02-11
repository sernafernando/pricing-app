"""
Modelos para configuración de markups de tienda
"""

from sqlalchemy import Column, Integer, String, Float, Boolean, DateTime, ForeignKey, Text
from sqlalchemy.sql import func
from sqlalchemy.orm import relationship
from app.core.database import Base


class MarkupTiendaBrand(Base):
    """
    Configuración de markup por marca para la tienda.
    Permite definir markups específicos para cada marca.
    """

    __tablename__ = "markups_tienda_brand"

    id = Column(Integer, primary_key=True, index=True)
    comp_id = Column(Integer, nullable=False)
    brand_id = Column(Integer, nullable=False, index=True)
    brand_desc = Column(String(255), nullable=True)  # Desnormalizado para facilitar consultas

    # Markup en porcentaje (ej: 15.5 para 15.5%)
    markup_porcentaje = Column(Float, nullable=False)

    # Si está activo o no
    activo = Column(Boolean, default=True, nullable=False)

    # Notas opcionales
    notas = Column(Text, nullable=True)

    # Auditoría
    created_by_id = Column(Integer, ForeignKey("usuarios.id"), nullable=True)
    updated_by_id = Column(Integer, ForeignKey("usuarios.id"), nullable=True)
    created_at = Column(DateTime(timezone=True), server_default=func.now())
    updated_at = Column(DateTime(timezone=True), onupdate=func.now())

    # Relaciones
    created_by = relationship("Usuario", foreign_keys=[created_by_id])
    updated_by = relationship("Usuario", foreign_keys=[updated_by_id])

    def __repr__(self):
        return f"<MarkupTiendaBrand(brand_id={self.brand_id}, brand_desc='{self.brand_desc}', markup={self.markup_porcentaje}%)>"


class MarkupTiendaProducto(Base):
    """
    Configuración de markup por producto individual para la tienda.
    Permite definir markups específicos para productos individuales (sobrescribe el de marca).
    """

    __tablename__ = "markups_tienda_producto"

    id = Column(Integer, primary_key=True, index=True)
    item_id = Column(Integer, nullable=False, unique=True, index=True)
    codigo = Column(String(100), nullable=True)  # Desnormalizado
    descripcion = Column(String(500), nullable=True)  # Desnormalizado
    marca = Column(String(255), nullable=True)  # Desnormalizado

    # Markup en porcentaje (ej: 15.5 para 15.5%)
    markup_porcentaje = Column(Float, nullable=False)

    # Si está activo o no
    activo = Column(Boolean, default=True, nullable=False)

    # Notas opcionales
    notas = Column(Text, nullable=True)

    # Auditoría
    created_by_id = Column(Integer, ForeignKey("usuarios.id"), nullable=True)
    updated_by_id = Column(Integer, ForeignKey("usuarios.id"), nullable=True)
    created_at = Column(DateTime(timezone=True), server_default=func.now())
    updated_at = Column(DateTime(timezone=True), onupdate=func.now())

    # Relaciones
    created_by = relationship("Usuario", foreign_keys=[created_by_id])
    updated_by = relationship("Usuario", foreign_keys=[updated_by_id])

    def __repr__(self):
        return (
            f"<MarkupTiendaProducto(item_id={self.item_id}, codigo='{self.codigo}', markup={self.markup_porcentaje}%)>"
        )


class TiendaConfig(Base):
    """
    Configuración global para la tienda.
    Almacena settings como markup_web_tarjeta.
    """

    __tablename__ = "tienda_config"

    id = Column(Integer, primary_key=True, index=True)
    clave = Column(String(100), nullable=False, unique=True, index=True)
    valor = Column(Float, nullable=False, default=0)
    descripcion = Column(String(255), nullable=True)

    # Auditoría
    updated_by_id = Column(Integer, ForeignKey("usuarios.id"), nullable=True)
    updated_at = Column(DateTime(timezone=True), onupdate=func.now())

    updated_by = relationship("Usuario", foreign_keys=[updated_by_id])

    def __repr__(self):
        return f"<TiendaConfig(clave='{self.clave}', valor={self.valor})>"
