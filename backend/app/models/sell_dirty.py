"""`sell_dirty`: the sale lines whose sell-in / sell-out allocation must be
recomputed (sell-in-sell-out T4).

One row per sale line, keyed like `SellInConsumo` (`canal`, `venta_ref`):

- `ml`: `venta_ref` = `ml_sale_lines.item_row_id`, queued by
  `app.services.order_metrics.sale_lines_store.store_sale_lines` when a line
  appears, changes or disappears;
- `fuera` / `tn`: `venta_ref` = `it_transaction` of `ventas_fuera_ml_metricas`
  / `ventas_tienda_nube_metricas`, queued by row triggers
  (`app.services.sell.queue`).

`item_id` is the line's product when it was queued (its OLD product on a
delete). A line that moved to another product is queued under the NEW one: the
old product's allocation is found through the line's own `sell_in_consumos`.

A line is queued once: a new change re-queues it in place (`enqueued_at`
refreshed, `attempts`/`last_error` reset). `attempts`/`last_error` are for the
allocator's poison handling, same shape as `tp_cost_fill_queue`. The drain is
`sell.drain` (`app.workers.handlers.sell_drain`).
"""

from sqlalchemy import BigInteger, CheckConstraint, Column, DateTime, Integer, String, Text, text
from sqlalchemy.sql import func

from app.core.database import Base


class SellDirty(Base):
    __tablename__ = "sell_dirty"
    __table_args__ = (CheckConstraint("canal IN ('ml', 'fuera', 'tn')", name="ck_sell_dirty_canal"),)

    canal = Column(String(8), primary_key=True)
    venta_ref = Column(BigInteger, primary_key=True, autoincrement=False)
    item_id = Column(Integer, nullable=True)
    enqueued_at = Column(DateTime(timezone=True), nullable=False, server_default=func.now())
    attempts = Column(Integer, nullable=False, server_default=text("0"))
    last_error = Column(Text, nullable=True)
