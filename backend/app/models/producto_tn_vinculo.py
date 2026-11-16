"""The Tienda Nube product an ERP product is linked to BY HAND (abm-productos S12), keyed by its `item_id`.

The TN catalog sync links variants to the ERP by SKU on every run (`tienda_nube_productos.item_id`); a row here
overrides that match and is applied last on every run, so a manual link always wins
(`app.services.tienda_nube_sync_shared.aplicar_vinculos_manuales`). `tn_product_id` NULL means "explicitly not
linked". A TN product is linked by hand to one product at most. No foreign keys: the ERP and TN syncs own those tables.
"""

from sqlalchemy import Column, DateTime, Integer, UniqueConstraint, func

from app.core.database import Base


class ProductoTnVinculo(Base):
    __tablename__ = "producto_tn_vinculos"
    __table_args__ = (UniqueConstraint("tn_product_id", name="uq_producto_tn_vinculos_tn_product_id"),)

    item_id = Column(Integer, primary_key=True, autoincrement=False)
    tn_product_id = Column(Integer, nullable=True)  # tienda_nube_productos.product_id; NULL: explicitly unlinked
    updated_by = Column(Integer, nullable=True)  # usuarios.id
    updated_at = Column(DateTime(timezone=True), nullable=False, server_default=func.now(), onupdate=func.now())
