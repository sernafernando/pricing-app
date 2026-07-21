from sqlalchemy import Boolean, Column, DateTime, Integer, String
from sqlalchemy.sql import func

from app.core.database import Base


class MlPublicationLink(Base):
    """
    Scalar snapshot of ML `render`-only link fields per MLA
    (family_id/user_product_id/inventory_id/catalog fields).

    INTENTIONALLY SEPARATE from `tb_mercadolibre_items_publicados`: both ERP
    incremental sync scripts `setattr` every key in `item_dict` onto that
    table every 5 minutes, so any ML-API-only column added there would be
    NULLed on the very next sync pass. This table has its own writer
    (the publication-link backfill/sync service, PR1b) and is never touched
    by the ERP sync, so link data persists safely.
    """

    __tablename__ = "ml_publication_links"

    mla = Column(String(50), primary_key=True)
    family_id = Column(String(50), nullable=True, index=True)
    user_product_id = Column(String(50), nullable=True)
    inventory_id = Column(String(50), nullable=True)
    catalog_listing = Column(Boolean, nullable=True, default=False)
    catalog_product_id = Column(String(50), nullable=True)
    item_id = Column(Integer, nullable=True, index=True)
    fetched_at = Column(DateTime(timezone=True), nullable=True)

    created_at = Column(DateTime(timezone=True), server_default=func.now())
    updated_at = Column(DateTime(timezone=True), server_default=func.now(), onupdate=func.now())

    def __repr__(self) -> str:
        return f"<MlPublicationLink(mla={self.mla}, family_id={self.family_id})>"
