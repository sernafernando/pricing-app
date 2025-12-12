"""
Modelos para overrides manuales de datos en ventas
Estos datos NO se sobreescriben cuando se recalculan las métricas
"""
from sqlalchemy import Column, Integer, BigInteger, String, DateTime, ForeignKey, Numeric, Text
from sqlalchemy.sql import func
from sqlalchemy.orm import relationship
from app.core.database import Base


class VentaTiendaNubeOverride(Base):
    """Override manual de datos para ventas de Tienda Nube"""
    __tablename__ = "ventas_tienda_nube_override"

    id = Column(Integer, primary_key=True, index=True)
    it_transaction = Column(BigInteger, unique=True, index=True, nullable=False)

    # Campos corregibles - Producto
    codigo = Column(String(100), nullable=True)
    descripcion = Column(Text, nullable=True)
    marca = Column(String(255), nullable=True)
    categoria = Column(String(255), nullable=True)
    subcategoria = Column(String(255), nullable=True)

    # Campos corregibles - Cliente
    cliente = Column(String(255), nullable=True)

    # Campos corregibles - Montos
    cantidad = Column(Numeric(18, 4), nullable=True)
    precio_unitario = Column(Numeric(18, 2), nullable=True)
    costo_unitario = Column(Numeric(18, 6), nullable=True)

    # Auditoría
    usuario_id = Column(Integer, ForeignKey('usuarios.id'), nullable=True)
    created_at = Column(DateTime(timezone=True), server_default=func.now())
    updated_at = Column(DateTime(timezone=True), server_default=func.now(), onupdate=func.now())

    # Relación
    usuario = relationship("Usuario", backref="overrides_tn")

    def __repr__(self):
        return f"<VentaTiendaNubeOverride(it_transaction={self.it_transaction}, marca={self.marca})>"


class VentaFueraMLOverride(Base):
    """Override manual de datos para ventas fuera de ML"""
    __tablename__ = "ventas_fuera_ml_override"

    id = Column(Integer, primary_key=True, index=True)
    it_transaction = Column(BigInteger, unique=True, index=True, nullable=False)

    # Campos corregibles - Producto
    codigo = Column(String(100), nullable=True)
    descripcion = Column(Text, nullable=True)
    marca = Column(String(255), nullable=True)
    categoria = Column(String(255), nullable=True)
    subcategoria = Column(String(255), nullable=True)

    # Campos corregibles - Cliente
    cliente = Column(String(255), nullable=True)

    # Campos corregibles - Montos
    cantidad = Column(Numeric(18, 4), nullable=True)
    precio_unitario = Column(Numeric(18, 2), nullable=True)
    costo_unitario = Column(Numeric(18, 6), nullable=True)

    # Auditoría
    usuario_id = Column(Integer, ForeignKey('usuarios.id'), nullable=True)
    created_at = Column(DateTime(timezone=True), server_default=func.now())
    updated_at = Column(DateTime(timezone=True), server_default=func.now(), onupdate=func.now())

    # Relación
    usuario = relationship("Usuario", backref="overrides_fuera_ml")

    def __repr__(self):
        return f"<VentaFueraMLOverride(it_transaction={self.it_transaction}, marca={self.marca})>"
