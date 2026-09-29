"""Pack-aware enqueue + orphan group cleanup (ventas-ml-rediseno PR20, SM R12/R14).

This module REPLACES the body of `order_metrics_enqueue_orders_ops()` that
`triggers.py` (PR4) first defined. The triggers themselves are NOT touched:
`trg_order_metrics_orders_ops_{insert,update,delete}` already fire on the
right events -- the UPDATE one already lists `pack_id` in its `UPDATE OF`
columns and its `WHEN` already tests `OLD.pack_id IS DISTINCT FROM
NEW.pack_id`. Only the function they call needed to grow.

That distinction is what makes this cheap: `CREATE OR REPLACE FUNCTION` IS
idempotent, unlike `CREATE TRIGGER`. So this module's DDL can be re-applied
safely, and PR4's migration and its frozen copy stay untouched -- the
immutability contract in `triggers.py:22-33` is respected without having to
drop and recreate anything.

WHY THE FAN-OUT ALONE IS NOT ENOUGH (SM R14, the defect a review caught in
the plan before a line of this was written): the fan-out enqueues SURVIVING
siblings so their group record is recomputed. But a group whose LAST member
just left has no surviving sibling to enqueue, so nothing would ever revisit
it and its record would sit there forever holding the money of a sale that no
longer exists. KPI aggregation reads those records directly, so a leftover
record is money counted for something that is gone -- or counted twice.

Three cases, each of which leaves an orphan if only the fan-out is added:

  (a) a STANDALONE order joins a pack. Its own `"o:<order_id>"` record stays
      behind, and the same sale is then counted twice: once as that stale
      standalone group and once inside the pack.
  (b) the LAST member of a pack leaves or is deleted. No sibling remains, so
      `"p:<pack_id>"` keeps its last-known values indefinitely.
  (c) a STANDALONE order is deleted. `ml_order_metrics` goes with it through
      its FK cascade, but a record keyed by GROUP identity has no FK to
      cascade from.

The cleanup lives HERE, in SQL, rather than in the Python recompute, because
this trigger is the only place that sees the OLD and the NEW membership in
the same event. By the time the worker recomputes, `OLD.pack_id` is gone.
"""

from __future__ import annotations

from sqlalchemy.engine import Connection

_ORDERS_OPS_PACK_TRIGGER_SQL = """
CREATE OR REPLACE FUNCTION order_metrics_enqueue_orders_ops() RETURNS TRIGGER AS $trg$
DECLARE
    ids BIGINT[];
    sibling_ids BIGINT[];
    pack_sibling_ids BIGINT[];
    remaining INTEGER;
BEGIN
    IF TG_OP = 'DELETE' THEN
        -- Flex split divisor: a DELETE changes it for every SURVIVING
        -- sibling sharing OLD.shipping_id (F7 fix -- the divisor is
        -- `COUNT(order_id) GROUP BY shipping_id`, computed at read time).
        IF OLD.shipping_id IS NOT NULL THEN
            SELECT COALESCE(array_agg(order_id), ARRAY[]::BIGINT[]) INTO sibling_ids
            FROM ml_orders_ops
            WHERE shipping_id = OLD.shipping_id AND order_id <> OLD.order_id;
        ELSE
            sibling_ids := ARRAY[]::BIGINT[];
        END IF;

        -- PR20 (SM R12): the group loses a member, so every SURVIVING member
        -- of the same pack has to recompute -- their group record no longer
        -- covers the same set of orders.
        IF OLD.pack_id IS NOT NULL THEN
            SELECT COALESCE(array_agg(order_id), ARRAY[]::BIGINT[]) INTO pack_sibling_ids
            FROM ml_orders_ops
            WHERE pack_id = OLD.pack_id AND order_id <> OLD.order_id;
            sibling_ids := sibling_ids || pack_sibling_ids;
        END IF;

        -- PR20 (SM R14, case c): this order's own standalone group record can
        -- never be recomputed again -- the order is gone -- so it is removed
        -- here. `ml_order_metrics` goes through its FK cascade; a record keyed
        -- by group identity has no FK to cascade from.
        DELETE FROM ml_group_metrics WHERE group_key = 'o:' || OLD.order_id;

        -- PR20 (SM R14, case b): if that was the pack's LAST member, no
        -- sibling exists to enqueue and nothing would ever revisit the pack's
        -- record. Remove it instead of leaving it holding the money of a
        -- pedido that no longer has any orders.
        IF OLD.pack_id IS NOT NULL THEN
            SELECT COUNT(*) INTO remaining
            FROM ml_orders_ops
            WHERE pack_id = OLD.pack_id AND order_id <> OLD.order_id;
            IF remaining = 0 THEN
                DELETE FROM ml_group_metrics WHERE group_key = 'p:' || OLD.pack_id;
            END IF;
        END IF;

        PERFORM order_metrics_enqueue(ARRAY[OLD.order_id] || sibling_ids, 'ml_orders_ops_delete');
        RETURN OLD;
    END IF;

    ids := ARRAY[NEW.order_id];
    IF TG_OP = 'INSERT' THEN
        -- Flex split divisor: an INSERT changes it for every OTHER order
        -- already sharing NEW.shipping_id (F7 fix, same reasoning as DELETE).
        IF NEW.shipping_id IS NOT NULL THEN
            SELECT COALESCE(array_agg(order_id), ARRAY[]::BIGINT[]) INTO sibling_ids
            FROM ml_orders_ops
            WHERE shipping_id = NEW.shipping_id AND order_id <> NEW.order_id;
            ids := ids || sibling_ids;
        END IF;
        -- PR20 (SM R12): a new member changes what its pack covers, so every
        -- order already in NEW.pack_id recomputes too.
        IF NEW.pack_id IS NOT NULL THEN
            SELECT COALESCE(array_agg(order_id), ARRAY[]::BIGINT[]) INTO pack_sibling_ids
            FROM ml_orders_ops
            WHERE pack_id = NEW.pack_id AND order_id <> NEW.order_id;
            ids := ids || pack_sibling_ids;
        END IF;
    ELSIF TG_OP = 'UPDATE' THEN
        IF OLD.shipping_id IS DISTINCT FROM NEW.shipping_id THEN
            -- Flex split divisor: a shipping_id change also enqueues every OTHER
            -- order that shares OLD or NEW shipping_id (design D3 scope).
            SELECT COALESCE(array_agg(order_id), ARRAY[]::BIGINT[]) INTO sibling_ids
            FROM ml_orders_ops
            WHERE shipping_id IN (OLD.shipping_id, NEW.shipping_id) AND order_id <> NEW.order_id;
            ids := ids || sibling_ids;
        END IF;

        IF OLD.pack_id IS DISTINCT FROM NEW.pack_id THEN
            -- PR20 (SM R12): BOTH sides refresh. The pack it left no longer
            -- covers this order; the pack it joined now does.
            SELECT COALESCE(array_agg(order_id), ARRAY[]::BIGINT[]) INTO pack_sibling_ids
            FROM ml_orders_ops
            WHERE pack_id IN (OLD.pack_id, NEW.pack_id) AND order_id <> NEW.order_id;
            ids := ids || pack_sibling_ids;

            -- PR20 (SM R14, case a): the order used to be standalone and now
            -- belongs to a pack. Its own `"o:<id>"` record must go, or the sale
            -- is counted twice -- once as that stale standalone group and once
            -- inside the pack that now contains it.
            IF OLD.pack_id IS NULL AND NEW.pack_id IS NOT NULL THEN
                DELETE FROM ml_group_metrics WHERE group_key = 'o:' || NEW.order_id;
            END IF;

            -- PR20 (SM R14, case b): the order left a pack that now has no
            -- members at all. Same reasoning as the DELETE branch -- no
            -- sibling survives to enqueue, so the record is removed here.
            IF OLD.pack_id IS NOT NULL THEN
                SELECT COUNT(*) INTO remaining
                FROM ml_orders_ops
                WHERE pack_id = OLD.pack_id AND order_id <> NEW.order_id;
                IF remaining = 0 THEN
                    DELETE FROM ml_group_metrics WHERE group_key = 'p:' || OLD.pack_id;
                END IF;
            END IF;
        END IF;
    END IF;

    PERFORM order_metrics_enqueue(
        ids,
        CASE WHEN TG_OP = 'INSERT' THEN 'ml_orders_ops_insert' ELSE 'ml_orders_ops_update' END
    );
    RETURN NEW;
END;
$trg$ LANGUAGE plpgsql;
"""

_CREATE_STATEMENTS = (_ORDERS_OPS_PACK_TRIGGER_SQL,)


def create_pack_triggers(connection: Connection) -> None:
    """Replaces the orders-ops enqueue function with the pack-aware version.

    Creates no trigger: the three `trg_order_metrics_orders_ops_*` triggers
    from PR4 already point at this function name and already fire on the
    right events. Only the function body is replaced, and
    `CREATE OR REPLACE FUNCTION` is idempotent.
    """
    for statement in _CREATE_STATEMENTS:
        connection.exec_driver_sql(statement)
