from sqlalchemy import Column, Integer, String, Boolean, DateTime, Numeric, UniqueConstraint
from sqlalchemy.sql import func
from app.core.database import Base


class MLCatalogStatus(Base):
    """Estado de competencia en catálogos de MercadoLibre"""

    __tablename__ = "ml_catalog_status"

    id = Column(Integer, primary_key=True, index=True)
    mla = Column(String(20), nullable=False, index=True)
    catalog_product_id = Column(String(50))
    status = Column(String(50), index=True)  # winning, sharing_first_place, competing, not_listed
    current_price = Column(Numeric(18, 2))
    price_to_win = Column(Numeric(18, 2))
    visit_share = Column(String(20))
    consistent = Column(Boolean)
    competitors_sharing_first_place = Column(Integer)
    winner_mla = Column(String(20))
    winner_price = Column(Numeric(18, 2))
    fecha_consulta = Column(DateTime(timezone=True), nullable=False, server_default=func.now(), index=True)
    created_at = Column(DateTime(timezone=True), nullable=False, server_default=func.now())

    __table_args__ = (UniqueConstraint("mla", "fecha_consulta", name="uq_mla_fecha"),)

    def __repr__(self):
        return f"<MLCatalogStatus(mla={self.mla}, status={self.status}, price_to_win={self.price_to_win})>"
