"""The single writer of `ml_sale_lines` (see `app.models.ml_sale_line`).

Called by `store_order_metrics` -- so by the drain, and by every other caller
of it (`recompute_order_metrics`, `persistir_total_gauss`) -- inside the transaction that stores an order's
metrics: for the groups of the orders just stored it deletes their lines and
inserts what `sales.sale_lines` returns for those groups -- the very function
the board used to run live, with `queue=False` (the recompute queue is applied
at read time), `keyed=True` (a line needs its identity) and `narrow=True` (a
handful of groups is reached through the `pack_id` / `order_id` indexes, never
by hashing every order: the drain stores ~25 orders a second).

NEVER commits. PostgreSQL only, like the queue it hangs from.

The OLD group of an order that moved packs is not rewritten here: the capture
trigger (`order_metrics_enqueue_orders_ops`, PR20) already enqueues every
surviving member of the pack the order left, and each of them rewrites its group
when the drain stores it. A deleted order's lines go with it (the foreign key
below cascades).
"""

from __future__ import annotations

from functools import lru_cache
from typing import Iterable, Optional, Sequence

from sqlalchemy import String, bindparam, delete, func, insert, or_, select, text
from sqlalchemy.dialects.postgresql import ARRAY

from app.core.config import settings
from app.models.ml_sale_line import MlSaleLine
from app.services.ml_daily_metrics.sales import sale_lines

COLUMNS = (
    "item_row_id",
    "order_id",
    "group_key",
    "product",
    "mla",
    "group_date",
    "day",
    "qty",
    "gross",
    "tg",
    "mtg",
    "mcosto",
)


@lru_cache(maxsize=4)
def _insert_statement(seller: Optional[str]):
    """The `INSERT ... SELECT` of the derived lines, built ONCE per process with
    the group keys as a bound array. Building and compiling this statement
    costs ~10 ms of Python per call -- six times its execution on the server --
    and the drain stores ~25 orders a second. `seller` only keys the cache: the
    seller filter is read from the settings while the statement is built."""
    wanted = func.unnest(bindparam("keys", type_=ARRAY(String))).column_valued("group_key")
    lines = sale_lines(sqlite=False, groups=select(wanted), queue=False, keyed=True, narrow=True)
    return insert(MlSaleLine.__table__).from_select(list(COLUMNS), select(*(lines.c[name] for name in COLUMNS)))


def store_sale_lines(db, order_ids: Iterable[int], group_keys: Sequence[str]) -> None:
    """Replaces the lines of `group_keys`, and any line still held by one of
    `order_ids` under another group (an order that moved packs), with the
    freshly derived ones."""
    if db.get_bind().dialect.name != "postgresql":
        return
    order_ids = sorted({int(order_id) for order_id in order_ids})
    group_keys = sorted(set(group_keys))
    if not order_ids and not group_keys:
        return
    table = MlSaleLine.__table__
    # Two transactions storing members of the same pack rewrite the same group:
    # without a lock the second DELETE could miss the first one's uncommitted
    # INSERT and then collide with it on the primary key. One transaction-scoped
    # advisory lock per group (and per group an order is leaving), always taken in
    # sorted order, so they queue instead of deadlocking.
    db.execute(
        text(
            "SELECT pg_advisory_xact_lock(hashtextextended('ml_sale_lines:' || k, 0)) FROM ("
            "SELECT k FROM unnest(CAST(:keys AS text[])) AS k "
            "UNION SELECT group_key FROM ml_sale_lines WHERE order_id = ANY(CAST(:orders AS bigint[])) "
            "ORDER BY 1) AS locked"
        ),
        {"keys": group_keys, "orders": order_ids},
    )
    db.execute(delete(table).where(or_(table.c.group_key.in_(group_keys), table.c.order_id.in_(order_ids))))
    if group_keys:
        db.execute(_insert_statement(settings.ML_USER_ID), {"keys": group_keys})
