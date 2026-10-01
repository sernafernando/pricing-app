"""Daily per-product/per-publication sales rollup (ODD `metricas-ml-tablero`
T2) -- the read model behind the Métricas ML board.

ONE row per (product, MLA, accreditation day). SUMS only, never a
percentage: a markup is always `SUM(total_gauss) / SUM(costo)` over the
rows a caller selects, so any period/grouping the board asks for is exact.

- `product_item_id`: `ml_order_item_costos.producto_item_id` of the sold item;
  `0` when the item has no frozen cost row (no product resolved).
- `day`: the sale's GROUP accreditation day in the business timezone
  (`ml_group_metrics.group_date`, the same day rule as Ventas ML).
- `total_gauss`/`costo`: the order's stored Total Gauss and cost of goods,
  split across its items by each item's share of frozen cost
  (`costo_unitario_ars x quantity`); only orders with usable metrics add
  money, the rest count in `unresolved_orders`.
- The official store is NOT stored: the board resolves it from the
  publication's CURRENT `mlp_official_store_id`, so a publication that moves
  store takes its history with it (decision recorded in the ODD doc).

Written only by `app.services.ml_daily_metrics.rollup` (from
`order_metrics.store.store_order_metrics`, same transaction) and by
`app/scripts/backfill_ml_daily_metrics.py`.
"""

from __future__ import annotations

from sqlalchemy import Column, Date, DateTime, Index, Integer, Numeric, String, UniqueConstraint
from sqlalchemy.sql import func

from app.core.database import Base


class MlProductDailyMetrics(Base):
    __tablename__ = "ml_product_daily_metrics"
    __table_args__ = (
        UniqueConstraint("product_item_id", "mla", "day", name="uq_ml_product_daily_metrics_key"),
        # The board reads a date window; the refresh reads (mla, day).
        Index("ix_ml_product_daily_metrics_day", "day"),
        Index("ix_ml_product_daily_metrics_mla_day", "mla", "day"),
        # "actualizado hace": MAX(updated_at) (migration 20261001_ix_board_reads).
        Index("ix_ml_product_daily_metrics_updated_at", "updated_at"),
    )

    id = Column(Integer, primary_key=True)
    product_item_id = Column(Integer, nullable=False)
    mla = Column(String(20), nullable=False)
    day = Column(Date, nullable=False)

    units = Column(Integer, nullable=False, default=0)
    gross_ars = Column(Numeric(16, 2), nullable=False, default=0)
    total_gauss = Column(Numeric(16, 2), nullable=False, default=0)
    costo = Column(Numeric(16, 2), nullable=False, default=0)
    orders = Column(Integer, nullable=False, default=0)
    unresolved_orders = Column(Integer, nullable=False, default=0)
    last_sale_at = Column(DateTime(timezone=True), nullable=True)

    updated_at = Column(DateTime(timezone=True), nullable=False, server_default=func.now())
