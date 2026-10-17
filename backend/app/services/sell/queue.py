"""The `sell_dirty` queue (sell-in-sell-out T4): which sale lines must have
their sell-in / sell-out allocation recomputed. No cron: writers queue a line
and `pg_notify('sell_dirty')`, and `sell.drain` (worker REGISTRY) drains it.

The table is `app.models.sell_dirty` (migration `20261031_sell_dirty_queue`).

A claimed row is locked (`FOR UPDATE SKIP LOCKED`): a writer re-queueing the
same line waits for the drain's short transaction, then lands as a fresh row,
so a change made while the line was being processed is never lost.
"""

from __future__ import annotations

from typing import List, Tuple

from sqlalchemy import text
from sqlalchemy.orm import Session

CHANNEL = "sell_dirty"
BATCH_SIZE = 500

# Claim and ack in one statement: the INERT drain (T4) computes nothing, so
# there is nothing to settle between the claim and the delete. T5 splits it.
_ACK_SQL = text(
    """
DELETE FROM sell_dirty AS d
USING (
    SELECT canal, venta_ref FROM sell_dirty
    ORDER BY enqueued_at, canal, venta_ref
    LIMIT :limit
    FOR UPDATE SKIP LOCKED
) AS claimed
WHERE d.canal = claimed.canal AND d.venta_ref = claimed.venta_ref
RETURNING d.canal, d.venta_ref, d.item_id
"""
)


def ack_batch(db: Session, limit: int) -> List[Tuple[str, int, int]]:
    """Claims up to `limit` queued lines (skipping the ones another drain holds)
    and removes them. Returns `(canal, venta_ref, item_id)`. Does not commit."""
    return [tuple(row) for row in db.execute(_ACK_SQL, {"limit": limit})]
