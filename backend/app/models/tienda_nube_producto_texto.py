"""The name and description of each Tienda Nube product (abm-productos S12), one row per TN product (not per variant,
so the description is not repeated on every variant row of `tienda_nube_productos`).

Written by the same catalog sync pass that writes `tienda_nube_productos`, from the same `/products` response
(`app.services.tienda_nube_sync_shared.guardar_textos`). `descripcion_texto` is the HTML turned into plain text once
on write, for MercadoLibre, which accepts plain text only.
"""

from sqlalchemy import Column, DateTime, Integer, String, Text, func

from app.core.database import Base


class TiendaNubeProductoTexto(Base):
    __tablename__ = "tienda_nube_producto_textos"

    product_id = Column(Integer, primary_key=True, autoincrement=False)  # tienda_nube_productos.product_id
    nombre = Column(String(500), nullable=True)
    descripcion_html = Column(Text, nullable=True)  # NULL: TN sent no description
    descripcion_texto = Column(Text, nullable=False, server_default="")
    updated_at = Column(DateTime(timezone=True), nullable=False, server_default=func.now(), onupdate=func.now())
