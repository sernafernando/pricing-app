"""Frozen per-item cost snapshot (ml-ventas-modo-logistico, PR3, design D4).

Written ONLY by `services/ml_orders_ingestion/costeo_service.py::congelar()`,
INSERT-only via `ON CONFLICT DO NOTHING` (design D5) — a re-ingestion of the
same order/item NEVER rewrites an already-frozen row, so a later ERP cost
change can never leak into a sale that has already been costed. This keeps
the cost seam `MlOrderItemOps` already documents: ingestion of the order/
item rows themselves never reads ERP, and this table is the ONLY place ERP
cost data is joined in.

Nothing reads this table yet in this slice (PR3 is write-only by design —
see the tasks artifact: "merges EARLY... write-only, nothing reads it yet").
"""

from __future__ import annotations

from sqlalchemy import (
    BigInteger,
    Column,
    Date,
    DateTime,
    Integer,
    Numeric,
    String,
    UniqueConstraint,
)
from sqlalchemy.sql import func

from app.core.database import Base


class MlOrderItemCosto(Base):
    """One immutable row per (order_id, item_id, variation_id) — the frozen
    cost/IVA/exchange-rate snapshot for that order item at ingestion time."""

    __tablename__ = "ml_order_item_costos"
    __table_args__ = (
        UniqueConstraint(
            "order_id",
            "item_id",
            "variation_id",
            name="uq_ml_order_item_costos_order_item_variation",
            postgresql_nulls_not_distinct=True,
        ),
    )

    id = Column(Integer, primary_key=True, index=True)

    order_id = Column(BigInteger, nullable=False, index=True)
    item_id = Column(String(20), nullable=False, index=True)
    variation_id = Column(BigInteger, nullable=True)

    costo_origen = Column(Numeric(14, 4), nullable=False)
    moneda = Column(String(3), nullable=False)
    tipo_cambio = Column(Numeric(14, 4), nullable=True)
    tipo_cambio_fecha = Column(Date, nullable=True)
    costo_unitario_ars = Column(Numeric(14, 4), nullable=False)

    iva_pct = Column(Numeric(5, 2), nullable=False)
    precio_unitario = Column(Numeric(14, 2), nullable=False)

    fuente = Column(String(20), nullable=False)
    producto_item_id = Column(Integer, nullable=False)

    congelado_at = Column(DateTime(timezone=True), nullable=False, server_default=func.now())
