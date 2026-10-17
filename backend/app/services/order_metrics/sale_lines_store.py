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

Every line that appears, changes what the sell-in / sell-out allocators read
(`SELL_COLUMNS`) or disappears is queued in `sell_dirty` in the same
transaction (`app.services.sell.queue.enqueue_ml`, sell-in-sell-out T4). The
old lines come back from the DELETE and the new ones from the INSERT (both
`RETURNING`), so a rewrite that changes nothing queues nothing and costs no
extra query. A line deleted by the foreign-key cascade (its order deleted) is
NOT seen here.

The OLD group of an order that moved packs is not rewritten here: the capture
trigger (`order_metrics_enqueue_orders_ops`, PR20) already enqueues every
surviving member of the pack the order left, and each of them rewrites its group
when the drain stores it. A deleted order's lines go with it (the foreign key
below cascades).
"""

from __future__ import annotations

from functools import lru_cache
from typing import Iterable, Optional, Sequence

from sqlalchemy import (
    String,
    bindparam,
    case,
    column,
    delete,
    except_,
    func,
    null,
    or_,
    select,
    text,
    union_all,
    values,
)
from sqlalchemy.dialects.postgresql import ARRAY
from sqlalchemy.dialects.postgresql import insert as pg_insert

from app.core.config import settings
from app.models.ml_order_metrics import MlOrderMetrics
from app.models.ml_sale_line import MlSaleLine
from app.services.ml_daily_metrics.sales import sale_lines
from app.services.sell.queue import enqueue_ml

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

# The TP-Link shares (metricas-ml-tplink-mode P3), derived with `tp=True`.
TP_COLUMNS = ("tg_tp", "mtg_tp", "mcosto_tp")

# The `ml_order_metrics.formula_version` that introduced `TP_COLUMNS`. The
# divergence check compares them only for lines of orders stored at or above
# it: older lines carry NULL there by construction, and bringing them up to
# date is `order_metrics.reconcile`'s job (the version bump), not a divergence.
TP_FORMULA_VERSION = 7

# Everything a stored line carries.
STORED_COLUMNS = COLUMNS + TP_COLUMNS

# What the sell-in / sell-out allocators read from a line (product first): a
# line whose values here change is queued in `sell_dirty`.
SELL_COLUMNS = ("product", "qty", "day", "group_date", "gross", "tg", "mcosto")


def derive_sale_lines(group_keys: Sequence[str]):
    """The lines of `group_keys` as `sale_lines` derives them now (a subquery
    with `STORED_COLUMNS`): what the divergence check compares the stored lines with."""
    keys = values(column("group_key", String), name="wanted").data([(key,) for key in group_keys])
    return sale_lines(sqlite=False, groups=select(keys.c.group_key), queue=False, keyed=True, narrow=True, tp=True)


def _comparable(lines):
    """`STORED_COLUMNS` of `lines`, with the TP shares blanked (NULL) for an
    order stored below `TP_FORMULA_VERSION`, so only the Gauss columns of those
    lines are compared. EXCEPT treats NULL as equal to NULL."""
    metrics = MlOrderMetrics.__table__
    current = metrics.c.formula_version >= TP_FORMULA_VERSION
    return (
        select(
            *(lines.c[name] for name in COLUMNS),
            *(case((current, lines.c[name]), else_=null()).label(name) for name in TP_COLUMNS),
        )
        .select_from(lines)
        .outerjoin(metrics, metrics.c.order_id == lines.c.order_id)
    )


def diverging_groups(db, group_keys: Sequence[str]) -> list:
    """The groups, among `group_keys`, whose stored lines differ from a live
    derivation (a missing, an extra or a different line). Money, TP shares
    included, is compared by value."""
    if not group_keys:
        return []
    table = MlSaleLine.__table__
    live = _comparable(derive_sale_lines(group_keys))
    stored = _comparable(select(table).where(table.c.group_key.in_(group_keys)).subquery("stored"))
    both = union_all(except_(live, stored), except_(stored, live)).subquery("diff")
    return sorted(db.execute(select(both.c.group_key).distinct()).scalars().all())


@lru_cache(maxsize=4)
def _insert_statement(seller: Optional[str]):
    """The `INSERT ... SELECT` of the derived lines, built ONCE per process with
    the group keys as a bound array. Building and compiling this statement
    costs ~10 ms of Python per call -- six times its execution on the server --
    and the drain stores ~25 orders a second. `seller` only keys the cache: the
    seller filter is read from the settings while the statement is built."""
    wanted = func.unnest(bindparam("keys", type_=ARRAY(String))).column_valued("group_key")
    lines = sale_lines(sqlite=False, groups=select(wanted), queue=False, keyed=True, narrow=True, tp=True)
    statement = pg_insert(MlSaleLine.__table__).from_select(
        list(STORED_COLUMNS), select(*(lines.c[name] for name in STORED_COLUMNS))
    )
    # A sibling that JOINS the group is derived with it while its own lines are
    # still stored under its previous group: the line moves instead of colliding.
    table = MlSaleLine.__table__
    return statement.on_conflict_do_update(
        index_elements=["item_row_id"],
        set_={name: statement.excluded[name] for name in STORED_COLUMNS if name != "item_row_id"},
    ).returning(table.c.item_row_id, *(table.c[name] for name in SELL_COLUMNS))


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
    sell_values = (table.c.item_row_id, *(table.c[name] for name in SELL_COLUMNS))
    deleted = db.execute(
        delete(table)
        .where(or_(table.c.group_key.in_(group_keys), table.c.order_id.in_(order_ids)))
        .returning(*sell_values)
    )
    old = {row[0]: tuple(row[1:]) for row in deleted}
    new = {}
    if group_keys:
        new = {
            row[0]: tuple(row[1:]) for row in db.execute(_insert_statement(settings.ML_USER_ID), {"keys": group_keys})
        }
    # `values[0]` is the product: a line that disappeared is queued under its
    # old product, any other under its new one.
    changed = {ref: values[0] for ref, values in old.items() if new.get(ref) != values}
    changed.update((ref, values[0]) for ref, values in new.items() if old.get(ref) != values)
    enqueue_ml(db, list(changed.items()))
