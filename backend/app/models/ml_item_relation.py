from sqlalchemy import Column, Index, Integer, String, UniqueConstraint

from app.core.database import Base


class MlItemRelation(Base):
    """
    Junction table for ML `item_relations` (MLA -> related MLA edges),
    e.g. stock-synced "vinculada" publications.

    INTENTIONALLY SEPARATE from `tb_mercadolibre_items_publicados`: both ERP
    incremental sync scripts `setattr` every key in `item_dict` onto that
    table every 5 minutes, so any ML-API-only data added there would be
    clobbered on the very next sync pass. This table has its own writer
    (the publication-link backfill/sync service, PR1b) and is never touched
    by the ERP sync.
    """

    __tablename__ = "ml_item_relations"

    id = Column(Integer, primary_key=True)
    mla = Column(String(50), nullable=False, index=True)
    related_mla = Column(String(50), nullable=False, index=True)
    stock_relation = Column(Integer, nullable=True)
    variation_id = Column(String(50), nullable=True)

    __table_args__ = (
        UniqueConstraint("mla", "related_mla", name="uq_ml_item_relations_mla_related_mla"),
        Index("ix_ml_item_relations_mla_related_mla_lookup", "mla", "related_mla"),
    )

    def __repr__(self) -> str:
        return f"<MlItemRelation(mla={self.mla}, related_mla={self.related_mla})>"
