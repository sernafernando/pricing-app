"""Queue of items whose promo price columns must be recomputed now (promo-ml-precio-inmediato T1).

ml-webhook calls `POST /api/promociones/recompute-precios` after it updates the promo mirror of an
item; the endpoint upserts one row per `item_id` (so repeated notifications for the same item
collapse) and the `promo_price.recompute` worker handler (every 5 s) drains it with `recompute_item`. The
`sync_promo_prices` cron stays as the catch-up net for anything this path misses.
"""

from __future__ import annotations

from datetime import UTC, datetime

from sqlalchemy import Column, DateTime, Integer, Text

from app.core.database import Base


class PromoPriceRecomputeQueue(Base):
    """One pending recompute per item. `enqueued_at` is rewritten by every new request, so the
    worker only deletes the row it processed when nobody asked again meanwhile; `attempts` and
    `last_error` count failed runs, and an item is parked at `MAX_ATTEMPTS` until a new request."""

    __tablename__ = "promo_price_recompute_queue"

    item_id = Column(Integer, primary_key=True, autoincrement=False)
    enqueued_at = Column(DateTime(timezone=True), nullable=False, default=lambda: datetime.now(UTC))
    attempts = Column(Integer, nullable=False, default=0, server_default="0")
    last_error = Column(Text, nullable=True)
