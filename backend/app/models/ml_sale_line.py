"""The persisted per-sold-line base of the Métricas ML board (`ml_sale_lines`).

One row per sold item line of every accredited group: EXACTLY the output of
`app.services.ml_daily_metrics.sales.sale_lines` (the single definition of the
day, product, cancellation and money rules), computed with `queue=False` and
written by `app.services.order_metrics.sale_lines_store` in the SAME
transaction that stores an order's metrics (`store_order_metrics`, so the
`order_metrics.drain` and any other caller of it). Nothing else writes it. Whatever invalidates an order's metrics therefore invalidates
its lines, and a `CURRENT_FORMULA_VERSION` bump re-derives all of them through
`order_metrics.reconcile`.

Money columns are plain NUMERIC on purpose: an order's Total Gauss is split
across its items in fractions of a cent and the board SUMS them, so rounding
here would change the totals.

The recompute queue (`ml_order_metrics_dirty`) is NOT part of a row: an order
being recalculated has no money on the board, and the board applies that at
read time from the (small) queue, exactly as `sale_lines` does live.

Indexes, each with its plan:

- `ix_ml_sale_lines_group_date`: the board reads the lines of a range of
  accreditation days (`WHERE group_date >= ... AND group_date < ...`).
- `ix_ml_sale_lines_group_key`: the drain rewrites ONE group's lines
  (`DELETE ... WHERE group_key = ANY(...)`).
- `ix_ml_sale_lines_order_id`: an order that moved to another group drops its
  old lines (`DELETE ... WHERE order_id = ANY(...)`).
- `ix_ml_sale_lines_product_group_date`: a product's publication sub-rows
  (`WHERE product = ... AND group_date ...`) and its latest sale.
"""

from __future__ import annotations

from sqlalchemy import BigInteger, Column, Date, DateTime, ForeignKey, Index, Integer, Numeric, String

from app.core.database import Base


class MlSaleLine(Base):
    __tablename__ = "ml_sale_lines"
    __table_args__ = (
        Index("ix_ml_sale_lines_group_date", "group_date"),
        Index("ix_ml_sale_lines_group_key", "group_key"),
        Index("ix_ml_sale_lines_order_id", "order_id"),
        Index("ix_ml_sale_lines_product_group_date", "product", "group_date"),
    )

    # `ml_order_items_ops.id`: one line per sold item row. A deleted item (or
    # order) takes its line with it.
    item_row_id = Column(
        Integer, ForeignKey("ml_order_items_ops.id", ondelete="CASCADE"), primary_key=True, autoincrement=False
    )
    order_id = Column(BigInteger, nullable=False)
    group_key = Column(String(32), nullable=False)
    product = Column(Integer, nullable=False)
    mla = Column(String(20), nullable=False)
    group_date = Column(DateTime(timezone=True), nullable=False)
    day = Column(Date, nullable=False)
    qty = Column(Integer, nullable=False)
    gross = Column(Numeric, nullable=False)
    tg = Column(Numeric, nullable=False)
    mtg = Column(Numeric, nullable=False)
    mcosto = Column(Numeric, nullable=False)
