"""Our own product (Publicaciones ML T6): the manual SKU and EAN of an ERP product, keyed by its `item_id`.

Only what an operator typed is stored; the values the panel shows are computed on read
(`app.services.producto_propio_service`). When the ERP is replaced, this `item_id` becomes our own product id.
No foreign key to `productos_erp`: the ERP sync owns that table and must never be blocked by a row here.
"""

from sqlalchemy import Column, DateTime, Integer, String, func

from app.core.database import Base

# The longest SKU or EAN accepted: the width of the ERP `codigo` column the EAN defaults to.
MAX_CODE_LENGTH = 100


class ProductoPropio(Base):
    __tablename__ = "productos_propios"

    item_id = Column(Integer, primary_key=True, autoincrement=False)
    sku = Column(String(MAX_CODE_LENGTH), nullable=True)  # NULL: the SKU the linked publications share
    ean = Column(String(MAX_CODE_LENGTH), nullable=True)  # NULL: the ERP `codigo`
    updated_by = Column(Integer, nullable=True)  # usuarios.id of the last edit
    updated_at = Column(DateTime(timezone=True), nullable=False, server_default=func.now(), onupdate=func.now())
