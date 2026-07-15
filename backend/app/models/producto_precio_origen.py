"""Provenance table for price-column writers (manual edit vs promo).

Part of the promo-price-propagation feature (slice 2). One row per
(item_id, column_key) records which mechanism last set that price column,
so promo sync (slice 3/4) can arbitrate last-write-wins against manual edits.
"""

from datetime import UTC, datetime
from typing import Iterable, Optional

from sqlalchemy import Column, DateTime, ForeignKey, Integer, String, UniqueConstraint
from sqlalchemy.orm import Session

from app.core.database import Base


class ProductoPrecioOrigen(Base):
    """Tracks the origin ('manual' | 'promo') of each price column write.

    Unique on (item_id, column_key): there is exactly one *current* origin
    per column per product — every write upserts this row rather than
    inserting a new one.
    """

    __tablename__ = "producto_precio_origen"

    id = Column(Integer, primary_key=True, index=True)
    item_id = Column(Integer, ForeignKey("productos_erp.item_id"), nullable=False, index=True)
    column_key = Column(String(50), nullable=False)
    origen = Column(String(20), nullable=False)  # 'manual' | 'promo'
    promo_id = Column(String(50), nullable=True)
    mla = Column(String(50), nullable=True)
    fecha = Column(DateTime, nullable=False, default=lambda: datetime.now(UTC))

    __table_args__ = (
        UniqueConstraint("item_id", "column_key", name="uq_producto_precio_origen_item_column"),
    )


def upsert_origen_manual(
    db: Session,
    item_id: int,
    column_keys: Iterable[str],
    *,
    fecha: Optional[datetime] = None,
) -> None:
    """Tag each column in `column_keys` as manually-set for `item_id`.

    Upserts the (item_id, column_key) row: flips an existing row's origen
    back to 'manual' (clearing promo_id/mla) if a promo previously owned
    it, or inserts a new row otherwise. Does not commit — callers persist
    this in the same transaction as the price write it accompanies.
    """
    ts = fecha or datetime.now(UTC)
    for column_key in column_keys:
        existing = (
            db.query(ProductoPrecioOrigen)
            .filter(
                ProductoPrecioOrigen.item_id == item_id,
                ProductoPrecioOrigen.column_key == column_key,
            )
            .first()
        )
        if existing:
            existing.origen = "manual"
            existing.promo_id = None
            existing.mla = None
            existing.fecha = ts
        else:
            db.add(
                ProductoPrecioOrigen(
                    item_id=item_id,
                    column_key=column_key,
                    origen="manual",
                    promo_id=None,
                    mla=None,
                    fecha=ts,
                )
            )
