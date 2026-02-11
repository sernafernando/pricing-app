from sqlalchemy import Column, Integer, BigInteger, String, Numeric, DateTime, Text
from sqlalchemy.sql import func
from app.core.database import Base

class MLPublicationSnapshot(Base):
    """
    Modelo para guardar snapshots de publicaciones de MercadoLibre
    Permite comparar las campañas/listas actuales con las que tiene ML
    """
    __tablename__ = "ml_publication_snapshots"

    id = Column(Integer, primary_key=True, index=True)

    # Datos de la publicación
    mla_id = Column(String(50), nullable=False, index=True)  # MLA2016945208
    title = Column(Text)
    price = Column(Numeric(12, 2))
    base_price = Column(Numeric(12, 2))
    available_quantity = Column(Integer)
    sold_quantity = Column(Integer)
    status = Column(String(50))
    listing_type_id = Column(String(50))  # gold_pro, gold_premium, gold_special, etc.
    permalink = Column(String(500))

    # Datos de campaña y lista
    installments_campaign = Column(String(100))  # 3x_campaign, 6x_campaign, 12x_campaign, etc.

    # SKU del seller
    seller_sku = Column(String(100), index=True)

    # Item ID del ERP (si lo podemos obtener del SKU)
    item_id = Column(BigInteger, index=True)

    # Metadata del snapshot
    snapshot_date = Column(DateTime(timezone=True), server_default=func.now(), index=True)

    # Auditoría
    created_at = Column(DateTime(timezone=True), server_default=func.now())
    updated_at = Column(DateTime(timezone=True), server_default=func.now(), onupdate=func.now())

    def __repr__(self):
        return f"<MLPublicationSnapshot(mla_id={self.mla_id}, title={self.title[:50] if self.title else None}, campaign={self.installments_campaign})>"
