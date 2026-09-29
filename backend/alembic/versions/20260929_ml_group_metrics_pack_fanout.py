"""Pack-aware enqueue + orphan group cleanup (ventas-ml-rediseno PR20, SM R12/R14).

Frozen point-in-time copy of `app/services/order_metrics/triggers_pack.py`'s
DDL, per the migration immutability contract stated in `triggers.py:22-33`:
the Python module is the LIVE definition, and once a migration has inlined a
copy of it, that copy is never re-synced. A later PR that needs to change
this DDL adds its own module and its own migration with its own frozen copy.

This migration creates NO trigger. PR4's three
`trg_order_metrics_orders_ops_*` triggers already point at
`order_metrics_enqueue_orders_ops()` and already fire on the right events --
the UPDATE one already lists `pack_id` in its `UPDATE OF` columns. Only the
FUNCTION body is replaced, and `CREATE OR REPLACE FUNCTION` is idempotent,
unlike `CREATE TRIGGER`. That is why PR4's migration
(`20260923_ml_order_metrics_triggers_orders.py`) stays untouched here rather
than being dropped and recreated.

Downgrade restores PR4's function body verbatim -- also inlined frozen, for
the same reason: importing it from the live module would make this
migration's behaviour change under it.

Depends on `20260929_ml_group_metrics`: the new function body DELETEs from
`ml_group_metrics`, so that table must exist before this runs or every write
to `ml_orders_ops` would fail.
"""

from typing import Sequence, Union

from alembic import op

revision: str = "20260929_ml_group_metrics_pack_fanout"
down_revision: Union[str, None] = "20260929_ml_group_metrics"
branch_labels: Union[str, Sequence[str], None] = None
depends_on: Union[str, Sequence[str], None] = None


_PACK_AWARE_FUNCTION = """
CREATE OR REPLACE FUNCTION order_metrics_enqueue_orders_ops() RETURNS TRIGGER AS $trg$
DECLARE
    ids BIGINT[];
    sibling_ids BIGINT[];
    pack_sibling_ids BIGINT[];
    remaining INTEGER;
BEGIN
    IF TG_OP = 'DELETE' THEN
        IF OLD.shipping_id IS NOT NULL THEN
            SELECT COALESCE(array_agg(order_id), ARRAY[]::BIGINT[]) INTO sibling_ids
            FROM ml_orders_ops
            WHERE shipping_id = OLD.shipping_id AND order_id <> OLD.order_id;
        ELSE
            sibling_ids := ARRAY[]::BIGINT[];
        END IF;

        IF OLD.pack_id IS NOT NULL THEN
            SELECT COALESCE(array_agg(order_id), ARRAY[]::BIGINT[]) INTO pack_sibling_ids
            FROM ml_orders_ops
            WHERE pack_id = OLD.pack_id AND order_id <> OLD.order_id;
            sibling_ids := sibling_ids || pack_sibling_ids;
        END IF;

        DELETE FROM ml_group_metrics WHERE group_key = 'o:' || OLD.order_id;

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
        IF NEW.shipping_id IS NOT NULL THEN
            SELECT COALESCE(array_agg(order_id), ARRAY[]::BIGINT[]) INTO sibling_ids
            FROM ml_orders_ops
            WHERE shipping_id = NEW.shipping_id AND order_id <> NEW.order_id;
            ids := ids || sibling_ids;
        END IF;
        IF NEW.pack_id IS NOT NULL THEN
            SELECT COALESCE(array_agg(order_id), ARRAY[]::BIGINT[]) INTO pack_sibling_ids
            FROM ml_orders_ops
            WHERE pack_id = NEW.pack_id AND order_id <> NEW.order_id;
            ids := ids || pack_sibling_ids;
        END IF;
    ELSIF TG_OP = 'UPDATE' THEN
        IF OLD.shipping_id IS DISTINCT FROM NEW.shipping_id THEN
            SELECT COALESCE(array_agg(order_id), ARRAY[]::BIGINT[]) INTO sibling_ids
            FROM ml_orders_ops
            WHERE shipping_id IN (OLD.shipping_id, NEW.shipping_id) AND order_id <> NEW.order_id;
            ids := ids || sibling_ids;
        END IF;

        IF OLD.pack_id IS DISTINCT FROM NEW.pack_id THEN
            SELECT COALESCE(array_agg(order_id), ARRAY[]::BIGINT[]) INTO pack_sibling_ids
            FROM ml_orders_ops
            WHERE pack_id IN (OLD.pack_id, NEW.pack_id) AND order_id <> NEW.order_id;
            ids := ids || pack_sibling_ids;

            IF OLD.pack_id IS NULL AND NEW.pack_id IS NOT NULL THEN
                DELETE FROM ml_group_metrics WHERE group_key = 'o:' || NEW.order_id;
            END IF;

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

# PR4's body, frozen here so the downgrade does not depend on the live module.
_PR4_FUNCTION = """
CREATE OR REPLACE FUNCTION order_metrics_enqueue_orders_ops() RETURNS TRIGGER AS $trg$
DECLARE
    ids BIGINT[];
    sibling_ids BIGINT[];
BEGIN
    IF TG_OP = 'DELETE' THEN
        IF OLD.shipping_id IS NOT NULL THEN
            SELECT COALESCE(array_agg(order_id), ARRAY[]::BIGINT[]) INTO sibling_ids
            FROM ml_orders_ops
            WHERE shipping_id = OLD.shipping_id AND order_id <> OLD.order_id;
        ELSE
            sibling_ids := ARRAY[]::BIGINT[];
        END IF;
        PERFORM order_metrics_enqueue(ARRAY[OLD.order_id] || sibling_ids, 'ml_orders_ops_delete');
        RETURN OLD;
    END IF;

    ids := ARRAY[NEW.order_id];
    IF TG_OP = 'INSERT' THEN
        IF NEW.shipping_id IS NOT NULL THEN
            SELECT COALESCE(array_agg(order_id), ARRAY[]::BIGINT[]) INTO sibling_ids
            FROM ml_orders_ops
            WHERE shipping_id = NEW.shipping_id AND order_id <> NEW.order_id;
            ids := ids || sibling_ids;
        END IF;
    ELSIF TG_OP = 'UPDATE' AND OLD.shipping_id IS DISTINCT FROM NEW.shipping_id THEN
        SELECT COALESCE(array_agg(order_id), ARRAY[]::BIGINT[]) INTO sibling_ids
        FROM ml_orders_ops
        WHERE shipping_id IN (OLD.shipping_id, NEW.shipping_id) AND order_id <> NEW.order_id;
        ids := ids || sibling_ids;
    END IF;

    PERFORM order_metrics_enqueue(
        ids,
        CASE WHEN TG_OP = 'INSERT' THEN 'ml_orders_ops_insert' ELSE 'ml_orders_ops_update' END
    );
    RETURN NEW;
END;
$trg$ LANGUAGE plpgsql;
"""


def upgrade() -> None:
    op.execute(_PACK_AWARE_FUNCTION)


def downgrade() -> None:
    op.execute(_PR4_FUNCTION)
