"""
SQLAlchemy model for `productos_ageing`.

Stores ERP-computed ageing data (dias_sin_venta according to ERP's own
definition) for each product. Populated by `sync_ageing.py`; the ranking
endpoint LEFT JOINs this table so ageing_erp_dias is null at launch.

Table created by migration: 20260529_01_consultas_ageing_table_permiso.py
"""

from datetime import datetime, UTC

from sqlalchemy import Column, DateTime, Integer
from sqlalchemy.dialects.postgresql import JSONB

from app.core.database import Base


class ProductoAgeing(Base):
    """ERP-sourced ageing data for a product.

    ageing_dias: days-without-sale according to ERP logic (may differ from
        the app's own calculated_ageing_days which uses tb_item_transactions).
    ageing_payload: raw JSON from the ERP scriptAgeing response; structure
        TBD pending live inspection — stored as-is for forward compatibility.
    """

    __tablename__ = "productos_ageing"

    # Logical FK to productos_erp.item_id (NOT a DB-level constraint — see ADR-3
    # and migration 20260529_01: independent sync cadence, tolerates orphans via
    # LEFT JOIN). Keep this a plain PK so the model matches the actual schema and
    # does not drift on `alembic revision --autogenerate`.
    item_id = Column(Integer, primary_key=True)
    ageing_dias = Column(Integer, nullable=True)
    ageing_payload = Column(JSONB, nullable=True)
    # Nullable to match the migration (a row may predate its first sync).
    fecha_sync = Column(
        DateTime(timezone=True),
        nullable=True,
        default=lambda: datetime.now(UTC),
    )
    created_at = Column(
        DateTime(timezone=True),
        nullable=False,
        default=lambda: datetime.now(UTC),
    )
    updated_at = Column(
        DateTime(timezone=True),
        nullable=False,
        default=lambda: datetime.now(UTC),
        onupdate=lambda: datetime.now(UTC),
    )
