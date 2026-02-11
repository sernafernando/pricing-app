from sqlalchemy import Column, Integer, String, Numeric, DateTime, Boolean
from sqlalchemy.sql import func
from app.core.database import Base


class TiendaNubeProducto(Base):
    """
    Modelo para productos y variantes de Tienda Nube
    Almacena información de precios para comparar con pricing ML
    """

    __tablename__ = "tienda_nube_productos"

    id = Column(Integer, primary_key=True, index=True)

    # IDs de Tienda Nube
    product_id = Column(Integer, nullable=False, index=True)
    product_name = Column(String(500))
    variant_id = Column(Integer, nullable=False, index=True)
    variant_sku = Column(String(100), index=True)

    # Precios
    price = Column(Numeric(18, 2))  # Precio normal
    compare_at_price = Column(Numeric(18, 2))  # Precio comparativo (tachado)
    promotional_price = Column(Numeric(18, 2))  # Precio promocional

    # Relación con ERP (si existe)
    item_id = Column(Integer, index=True)  # FK a productos_erp.item_id

    # Metadatos
    activo = Column(Boolean, default=True)
    fecha_sync = Column(DateTime(timezone=True), server_default=func.now())
    fecha_actualizacion = Column(DateTime(timezone=True), server_default=func.now(), onupdate=func.now())

    # Índice único para evitar duplicados
    __table_args__ = (
        # Un producto puede tener múltiples variantes, pero cada variante es única
        # product_id + variant_id debe ser único
    )

    def __repr__(self):
        return f"<TiendaNubeProducto(product_id={self.product_id}, variant_id={self.variant_id}, sku={self.variant_sku}, price={self.price})>"
