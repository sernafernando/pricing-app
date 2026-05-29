"""
SQLAlchemy model for `productos_ageing`.

Stores ERP-computed ageing data (dias_sin_venta according to ERP's own
definition) for each product. Populated by `sync_ageing.py`; the ranking
endpoint LEFT JOINs this table so ageing_erp_dias is null at launch.

Table created by migration: 20260529_01_consultas_ageing_table_permiso.py
"""

from datetime import datetime, UTC

from sqlalchemy import Column, DateTime, ForeignKey, Integer
from sqlalchemy.dialects.postgresql import JSONB
from sqlalchemy.orm import relationship

from app.core.database import Base


class ProductoAgeing(Base):
    """ERP-sourced ageing data for a product.

    ageing_dias: days-without-sale according to ERP logic (may differ from
        the app's own calculated_ageing_days which uses tb_item_transactions).
    ageing_payload: raw JSON from the ERP scriptAgeing response; structure
        TBD pending live inspection — stored as-is for forward compatibility.
    """

    __tablename__ = "productos_ageing"

    item_id = Column(
        Integer,
        ForeignKey("productos_erp.item_id", ondelete="CASCADE"),
        primary_key=True,
        nullable=False,
    )
    ageing_dias = Column(Integer, nullable=True)
    ageing_payload = Column(JSONB, nullable=True)
    fecha_sync = Column(
        DateTime(timezone=True),
        nullable=False,
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

    # Relationship back to ProductoERP (optional — useful for eager loading)
    producto = relationship(
        "ProductoERP",
        backref="ageing",
        foreign_keys=[item_id],
    )
