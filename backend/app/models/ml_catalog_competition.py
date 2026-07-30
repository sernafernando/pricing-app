from sqlalchemy import Column, Integer, String, DateTime, Numeric, UniqueConstraint
from sqlalchemy.dialects.postgresql import JSONB
from sqlalchemy.sql import func
from app.core.database import Base


class MLCatalogCompetition(Base):
    """Snapshot-per-fetch of catalog-competition data for one MLA.

    One row per consultation (never updated in place), unique on
    (mla, fecha_consulta). Read path is exclusively the
    `v_ml_catalog_competition_latest` view (see
    `20260731_ml_catalog_competition` migration), never this table
    directly, except by the writer.
    """

    __tablename__ = "ml_catalog_competition"

    # No single-column indexes are declared here on purpose: `id` is already
    # the primary key, and `mla` is the leading column of the composite
    # idx_mlcc_mla_fecha created by the migration, which serves both the
    # DISTINCT ON of the latest view and per-MLA lookups.
    id = Column(Integer, primary_key=True)
    mla = Column(String(20), nullable=False)
    fecha_consulta = Column(DateTime(timezone=True), nullable=False, server_default=func.now())
    catalog_product_id = Column(String(50), nullable=True)
    # ok | not_catalog | error — non-catalog MLAs and transport failures
    # are first-class stored facts, not silently dropped rows.
    fetch_status = Column(String(20), nullable=False)
    our_item_id = Column(String(20), nullable=True)
    our_seller_id = Column(String(32), nullable=True)
    our_price = Column(Numeric(18, 2), nullable=True)
    our_currency_id = Column(String(8), nullable=True)
    our_bucket_key = Column(String(64), nullable=True)
    # Dialect-neutral default on purpose. The migration's DDL uses
    # '[]'::jsonb, but this model must stay creatable by
    # Base.metadata.create_all() on SQLite, which the test suite uses
    # (tests/conftest.py) — a "::jsonb" cast there fails with
    # "unrecognized token: :". Rendering "DEFAULT '[]'" works on both, and
    # alembic/env.py does not set compare_server_default (Alembic defaults
    # it to False), so the difference from the DDL never reaches autogenerate.
    competitors = Column(JSONB, nullable=False, server_default="[]")
    competitor_count = Column(Integer, nullable=False, server_default="0")
    source_payload_hash = Column(String(64), nullable=True)
    error_detail = Column(String(500), nullable=True)
    created_at = Column(DateTime(timezone=True), nullable=False, server_default=func.now())

    __table_args__ = (UniqueConstraint("mla", "fecha_consulta", name="uq_ml_catalog_competition_mla_fecha"),)

    def __repr__(self):
        return f"<MLCatalogCompetition(mla={self.mla}, fetch_status={self.fetch_status}, fecha_consulta={self.fecha_consulta})>"
