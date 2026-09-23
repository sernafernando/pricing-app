"""order_metrics enqueue functions + per-order row triggers (ventas-ml-rediseno PR4)

Revision ID: 20260923_ml_order_metrics_triggers_orders
Revises: 20260922_ix_producto_item_id
Create Date: 2026-09-23

Design D3, D7, D8. Postgres-only: two PL/pgSQL enqueue helpers
(`order_metrics_enqueue` for input writes, `order_metrics_enqueue_system`
for reconcile/divergence) plus row-level triggers on the six per-order
input tables (`ml_orders_ops`, `ml_order_items_ops`, `ml_order_item_costos`,
`ml_payments_ops`, `ml_payment_charges`, `ml_shipments_ops`).

The DDL below is a FROZEN copy, inlined at authoring time, of what
`app/services/order_metrics/triggers.py::create_triggers`/`drop_triggers`
produced as of this revision -- it is NEVER imported from that module
(review finding F4). Migrations must be immutable: `CREATE TRIGGER` is not
idempotent, so if a later PR appends to that module's live statement list,
importing it here would make a fresh `alembic upgrade` create the LATER
PR's triggers inside THIS revision, and the later PR's own migration would
then fail with `trigger already exists` -- this revision would silently
stop meaning what it meant when it ran in production. The app-code module
stays the single source of truth for what the CURRENT test fixtures
(`tests/conftest.py::pg_order_metrics_triggers_engine`) and any later
migration apply going forward; this file is a point-in-time snapshot,
following this repo's own convention of inlining raw `op.execute()` SQL for
trigger DDL (see `20251226_trigger_descuento_01.py`) rather than importing
shared helpers into a migration.

This is the ONLY writer that starts producing dirty rows in production: the
worker (PR2/PR3) and its `order_metrics.drain` handler are already deployed
and idle. The moment this migration lands, real enqueues start flowing.

Applied via explicit `op.execute()` calls below, not an `after_create`
listener -- there is no SQLAlchemy metadata event involved on either side
(migration or test fixture).
"""

from __future__ import annotations

from typing import Sequence, Union

from alembic import op

# revision identifiers, used by Alembic.
revision: str = "20260923_ml_order_metrics_triggers_orders"
down_revision: Union[str, None] = "20260922_ix_producto_item_id"
branch_labels: Union[str, Sequence[str], None] = None
depends_on: Union[str, Sequence[str], None] = None


_ENQUEUE_FUNCTIONS_SQL = """
CREATE OR REPLACE FUNCTION order_metrics_enqueue(ids BIGINT[], reason TEXT)
RETURNS VOID AS $order_metrics_enqueue$
BEGIN
    IF ids IS NULL OR array_length(ids, 1) IS NULL THEN
        RETURN;
    END IF;
    INSERT INTO ml_order_metrics_dirty (order_id, version, reason, enqueued_at, attempts, last_error, suspect)
    SELECT DISTINCT x, 1, reason, now(), 0, NULL, false FROM unnest(ids) AS x ORDER BY x
    ON CONFLICT (order_id) DO UPDATE SET
        version = ml_order_metrics_dirty.version + 1,
        enqueued_at = now(),
        reason = EXCLUDED.reason,
        attempts = 0,
        last_error = NULL,
        suspect = false;
    PERFORM pg_notify('order_metrics_dirty', '');
END;
$order_metrics_enqueue$ LANGUAGE plpgsql;
"""

_ENQUEUE_SYSTEM_FUNCTION_SQL = """
CREATE OR REPLACE FUNCTION order_metrics_enqueue_system(ids BIGINT[], reason TEXT)
RETURNS VOID AS $order_metrics_enqueue_system$
BEGIN
    IF ids IS NULL OR array_length(ids, 1) IS NULL THEN
        RETURN;
    END IF;
    INSERT INTO ml_order_metrics_dirty (order_id, version, reason, enqueued_at, attempts, last_error, suspect)
    SELECT DISTINCT x, 1, reason, now(), 0, NULL, false FROM unnest(ids) AS x
    ON CONFLICT (order_id) DO NOTHING;
    PERFORM pg_notify('order_metrics_dirty', '');
END;
$order_metrics_enqueue_system$ LANGUAGE plpgsql;
"""

_ORDERS_OPS_TRIGGER_SQL = """
CREATE OR REPLACE FUNCTION order_metrics_enqueue_orders_ops() RETURNS TRIGGER AS $trg$
DECLARE
    ids BIGINT[];
    sibling_ids BIGINT[];
BEGIN
    IF TG_OP = 'DELETE' THEN
        PERFORM order_metrics_enqueue(ARRAY[OLD.order_id], 'ml_orders_ops_delete');
        RETURN OLD;
    END IF;

    ids := ARRAY[NEW.order_id];
    -- Flex split divisor: a shipping_id change also enqueues every OTHER
    -- order that shares OLD or NEW shipping_id (design D3 scope).
    IF TG_OP = 'UPDATE' AND OLD.shipping_id IS DISTINCT FROM NEW.shipping_id THEN
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

CREATE TRIGGER trg_order_metrics_orders_ops_insert
AFTER INSERT ON ml_orders_ops
FOR EACH ROW EXECUTE FUNCTION order_metrics_enqueue_orders_ops();

CREATE TRIGGER trg_order_metrics_orders_ops_update
AFTER UPDATE OF shipping_id, date_created, has_no_shipping_tag, pack_id ON ml_orders_ops
FOR EACH ROW WHEN (
    OLD.shipping_id IS DISTINCT FROM NEW.shipping_id
    OR OLD.date_created IS DISTINCT FROM NEW.date_created
    OR OLD.has_no_shipping_tag IS DISTINCT FROM NEW.has_no_shipping_tag
    OR OLD.pack_id IS DISTINCT FROM NEW.pack_id
)
EXECUTE FUNCTION order_metrics_enqueue_orders_ops();

CREATE TRIGGER trg_order_metrics_orders_ops_delete
AFTER DELETE ON ml_orders_ops
FOR EACH ROW EXECUTE FUNCTION order_metrics_enqueue_orders_ops();
"""

_ORDER_ITEMS_OPS_TRIGGER_SQL = """
CREATE OR REPLACE FUNCTION order_metrics_enqueue_order_items_ops() RETURNS TRIGGER AS $trg$
BEGIN
    IF TG_OP = 'DELETE' THEN
        PERFORM order_metrics_enqueue(ARRAY[OLD.order_id], 'ml_order_items_ops_delete');
        RETURN OLD;
    END IF;
    PERFORM order_metrics_enqueue(
        ARRAY[NEW.order_id],
        CASE WHEN TG_OP = 'INSERT' THEN 'ml_order_items_ops_insert' ELSE 'ml_order_items_ops_update' END
    );
    RETURN NEW;
END;
$trg$ LANGUAGE plpgsql;

CREATE TRIGGER trg_order_metrics_items_ops_insert
AFTER INSERT ON ml_order_items_ops
FOR EACH ROW EXECUTE FUNCTION order_metrics_enqueue_order_items_ops();

-- Read set (design D7 chain): quantity/unit_price/full_unit_price/sale_fee
-- feed the neto and cost calculations; title/listing_type_id/seller_sku/
-- raw_item do not.
CREATE TRIGGER trg_order_metrics_items_ops_update
AFTER UPDATE OF quantity, unit_price, full_unit_price, sale_fee ON ml_order_items_ops
FOR EACH ROW WHEN (
    OLD.quantity IS DISTINCT FROM NEW.quantity
    OR OLD.unit_price IS DISTINCT FROM NEW.unit_price
    OR OLD.full_unit_price IS DISTINCT FROM NEW.full_unit_price
    OR OLD.sale_fee IS DISTINCT FROM NEW.sale_fee
)
EXECUTE FUNCTION order_metrics_enqueue_order_items_ops();

CREATE TRIGGER trg_order_metrics_items_ops_delete
AFTER DELETE ON ml_order_items_ops
FOR EACH ROW EXECUTE FUNCTION order_metrics_enqueue_order_items_ops();
"""

_ORDER_ITEM_COSTOS_TRIGGER_SQL = """
CREATE OR REPLACE FUNCTION order_metrics_enqueue_order_item_costos() RETURNS TRIGGER AS $trg$
BEGIN
    IF TG_OP = 'DELETE' THEN
        PERFORM order_metrics_enqueue(ARRAY[OLD.order_id], 'ml_order_item_costos_delete');
        RETURN OLD;
    END IF;
    PERFORM order_metrics_enqueue(
        ARRAY[NEW.order_id],
        CASE WHEN TG_OP = 'INSERT' THEN 'ml_order_item_costos_insert' ELSE 'ml_order_item_costos_update' END
    );
    RETURN NEW;
END;
$trg$ LANGUAGE plpgsql;

CREATE TRIGGER trg_order_metrics_item_costos_insert
AFTER INSERT ON ml_order_item_costos
FOR EACH ROW EXECUTE FUNCTION order_metrics_enqueue_order_item_costos();

-- The table is INSERT-only by writer convention (`costeo_service.congelar`,
-- ON CONFLICT DO NOTHING) but the trigger still covers UPDATE/DELETE so a
-- future or manual write is not a silent staleness hole.
CREATE TRIGGER trg_order_metrics_item_costos_update
AFTER UPDATE OF costo_unitario_ars, iva_pct, precio_unitario ON ml_order_item_costos
FOR EACH ROW WHEN (
    OLD.costo_unitario_ars IS DISTINCT FROM NEW.costo_unitario_ars
    OR OLD.iva_pct IS DISTINCT FROM NEW.iva_pct
    OR OLD.precio_unitario IS DISTINCT FROM NEW.precio_unitario
)
EXECUTE FUNCTION order_metrics_enqueue_order_item_costos();

CREATE TRIGGER trg_order_metrics_item_costos_delete
AFTER DELETE ON ml_order_item_costos
FOR EACH ROW EXECUTE FUNCTION order_metrics_enqueue_order_item_costos();
"""

_PAYMENTS_OPS_TRIGGER_SQL = """
CREATE OR REPLACE FUNCTION order_metrics_enqueue_payments_ops() RETURNS TRIGGER AS $trg$
DECLARE
    ids BIGINT[];
BEGIN
    IF TG_OP = 'DELETE' THEN
        PERFORM order_metrics_enqueue(ARRAY[OLD.order_id], 'ml_payments_ops_delete');
        RETURN OLD;
    END IF;
    IF TG_OP = 'UPDATE' AND OLD.order_id IS DISTINCT FROM NEW.order_id THEN
        ids := ARRAY[OLD.order_id, NEW.order_id];
    ELSE
        ids := ARRAY[NEW.order_id];
    END IF;
    PERFORM order_metrics_enqueue(
        ids,
        CASE WHEN TG_OP = 'INSERT' THEN 'ml_payments_ops_insert' ELSE 'ml_payments_ops_update' END
    );
    RETURN NEW;
END;
$trg$ LANGUAGE plpgsql;

CREATE TRIGGER trg_order_metrics_payments_ops_insert
AFTER INSERT ON ml_payments_ops
FOR EACH ROW EXECUTE FUNCTION order_metrics_enqueue_payments_ops();

CREATE TRIGGER trg_order_metrics_payments_ops_update
AFTER UPDATE OF status, net_received_amount, transaction_amount_refunded, shipping_amount, order_id
ON ml_payments_ops
FOR EACH ROW WHEN (
    OLD.status IS DISTINCT FROM NEW.status
    OR OLD.net_received_amount IS DISTINCT FROM NEW.net_received_amount
    OR OLD.transaction_amount_refunded IS DISTINCT FROM NEW.transaction_amount_refunded
    OR OLD.shipping_amount IS DISTINCT FROM NEW.shipping_amount
    OR OLD.order_id IS DISTINCT FROM NEW.order_id
)
EXECUTE FUNCTION order_metrics_enqueue_payments_ops();

CREATE TRIGGER trg_order_metrics_payments_ops_delete
AFTER DELETE ON ml_payments_ops
FOR EACH ROW EXECUTE FUNCTION order_metrics_enqueue_payments_ops();
"""

_PAYMENT_CHARGES_TRIGGER_SQL = """
-- `payment_id` itself is part of the read set: `compute_breakdown` /
-- `compute_neto_by_order_ids` (breakdown_service.py) join a charge to its
-- order THROUGH `payment_id` -- it is not just a foreign key, it decides
-- WHICH order's net this charge counts toward. Moving a charge to a
-- different payment moves it out of one order's read set and into
-- another's, so both the losing (OLD) and gaining (NEW) order must be
-- enqueued -- an UPDATE that only enqueued NEW.payment_id's order would
-- leave the OLD order silently stale.
CREATE OR REPLACE FUNCTION order_metrics_enqueue_payment_charges() RETURNS TRIGGER AS $trg$
DECLARE
    resolved_order_id BIGINT;
    old_order_id BIGINT;
BEGIN
    IF TG_OP = 'DELETE' THEN
        SELECT order_id INTO resolved_order_id FROM ml_payments_ops WHERE payment_id = OLD.payment_id;
        IF resolved_order_id IS NOT NULL THEN
            PERFORM order_metrics_enqueue(ARRAY[resolved_order_id], 'ml_payment_charges_delete');
        END IF;
        RETURN OLD;
    END IF;

    SELECT order_id INTO resolved_order_id FROM ml_payments_ops WHERE payment_id = NEW.payment_id;

    IF TG_OP = 'UPDATE' AND OLD.payment_id IS DISTINCT FROM NEW.payment_id THEN
        SELECT order_id INTO old_order_id FROM ml_payments_ops WHERE payment_id = OLD.payment_id;
        IF old_order_id IS NOT NULL AND old_order_id IS DISTINCT FROM resolved_order_id THEN
            PERFORM order_metrics_enqueue(ARRAY[old_order_id], 'ml_payment_charges_update');
        END IF;
    END IF;

    IF resolved_order_id IS NOT NULL THEN
        PERFORM order_metrics_enqueue(
            ARRAY[resolved_order_id],
            CASE WHEN TG_OP = 'INSERT' THEN 'ml_payment_charges_insert' ELSE 'ml_payment_charges_update' END
        );
    END IF;
    RETURN NEW;
END;
$trg$ LANGUAGE plpgsql;

CREATE TRIGGER trg_order_metrics_payment_charges_insert
AFTER INSERT ON ml_payment_charges
FOR EACH ROW EXECUTE FUNCTION order_metrics_enqueue_payment_charges();

CREATE TRIGGER trg_order_metrics_payment_charges_update
AFTER UPDATE OF amount, refunded, type, name, payment_id ON ml_payment_charges
FOR EACH ROW WHEN (
    OLD.amount IS DISTINCT FROM NEW.amount
    OR OLD.refunded IS DISTINCT FROM NEW.refunded
    OR OLD.type IS DISTINCT FROM NEW.type
    OR OLD.name IS DISTINCT FROM NEW.name
    OR OLD.payment_id IS DISTINCT FROM NEW.payment_id
)
EXECUTE FUNCTION order_metrics_enqueue_payment_charges();

CREATE TRIGGER trg_order_metrics_payment_charges_delete
AFTER DELETE ON ml_payment_charges
FOR EACH ROW EXECUTE FUNCTION order_metrics_enqueue_payment_charges();
"""

_SHIPMENTS_OPS_TRIGGER_SQL = """
-- `compute_breakdown`/`_resolve_modes` (breakdown_service.py) resolve
-- shipments by `MlShipmentOps.shipment_id IN (<orders' shipping_id>)`,
-- NEVER by `ml_shipments_ops.order_id` -- that column can be NULL or can
-- name only ONE of several orders sharing the shipment (a pack, or a
-- shared Flex label). The real read-set owners are every
-- `ml_orders_ops` row whose `shipping_id` equals this shipment's id, the
-- same shape `order_metrics_enqueue_orders_ops` already uses for its own
-- sibling fanout.
CREATE OR REPLACE FUNCTION order_metrics_enqueue_shipments_ops() RETURNS TRIGGER AS $trg$
DECLARE
    ids BIGINT[];
BEGIN
    SELECT COALESCE(array_agg(order_id), ARRAY[]::BIGINT[]) INTO ids
    FROM ml_orders_ops
    WHERE shipping_id = COALESCE(NEW.shipment_id, OLD.shipment_id);

    IF TG_OP = 'DELETE' THEN
        PERFORM order_metrics_enqueue(ids, 'ml_shipments_ops_delete');
        RETURN OLD;
    END IF;

    PERFORM order_metrics_enqueue(
        ids,
        CASE WHEN TG_OP = 'INSERT' THEN 'ml_shipments_ops_insert' ELSE 'ml_shipments_ops_update' END
    );
    RETURN NEW;
END;
$trg$ LANGUAGE plpgsql;

CREATE TRIGGER trg_order_metrics_shipments_ops_insert
AFTER INSERT ON ml_shipments_ops
FOR EACH ROW EXECUTE FUNCTION order_metrics_enqueue_shipments_ops();

-- Only logistic_type/receiver_address are in the metrics read set;
-- sender_cost/receiver_cost/raw_costs stay trigger-free (`_sync_shipment_costs`
-- is a DIFFERENT writer path -- design D3 negative scenario).
CREATE TRIGGER trg_order_metrics_shipments_ops_update
AFTER UPDATE OF logistic_type, receiver_address ON ml_shipments_ops
FOR EACH ROW WHEN (
    OLD.logistic_type IS DISTINCT FROM NEW.logistic_type
    OR OLD.receiver_address IS DISTINCT FROM NEW.receiver_address
)
EXECUTE FUNCTION order_metrics_enqueue_shipments_ops();

CREATE TRIGGER trg_order_metrics_shipments_ops_delete
AFTER DELETE ON ml_shipments_ops
FOR EACH ROW EXECUTE FUNCTION order_metrics_enqueue_shipments_ops();
"""

# Order matters: functions before the triggers that call them; each table's
# own function before its own triggers. FROZEN at this revision -- never
# edited after release; a later PR's DDL changes get their OWN migration.
_CREATE_STATEMENTS = [
    _ENQUEUE_FUNCTIONS_SQL,
    _ENQUEUE_SYSTEM_FUNCTION_SQL,
    _ORDERS_OPS_TRIGGER_SQL,
    _ORDER_ITEMS_OPS_TRIGGER_SQL,
    _ORDER_ITEM_COSTOS_TRIGGER_SQL,
    _PAYMENTS_OPS_TRIGGER_SQL,
    _PAYMENT_CHARGES_TRIGGER_SQL,
    _SHIPMENTS_OPS_TRIGGER_SQL,
]

_DROP_STATEMENTS = [
    "DROP TRIGGER IF EXISTS trg_order_metrics_shipments_ops_delete ON ml_shipments_ops",
    "DROP TRIGGER IF EXISTS trg_order_metrics_shipments_ops_update ON ml_shipments_ops",
    "DROP TRIGGER IF EXISTS trg_order_metrics_shipments_ops_insert ON ml_shipments_ops",
    "DROP FUNCTION IF EXISTS order_metrics_enqueue_shipments_ops()",
    "DROP TRIGGER IF EXISTS trg_order_metrics_payment_charges_delete ON ml_payment_charges",
    "DROP TRIGGER IF EXISTS trg_order_metrics_payment_charges_update ON ml_payment_charges",
    "DROP TRIGGER IF EXISTS trg_order_metrics_payment_charges_insert ON ml_payment_charges",
    "DROP FUNCTION IF EXISTS order_metrics_enqueue_payment_charges()",
    "DROP TRIGGER IF EXISTS trg_order_metrics_payments_ops_delete ON ml_payments_ops",
    "DROP TRIGGER IF EXISTS trg_order_metrics_payments_ops_update ON ml_payments_ops",
    "DROP TRIGGER IF EXISTS trg_order_metrics_payments_ops_insert ON ml_payments_ops",
    "DROP FUNCTION IF EXISTS order_metrics_enqueue_payments_ops()",
    "DROP TRIGGER IF EXISTS trg_order_metrics_item_costos_delete ON ml_order_item_costos",
    "DROP TRIGGER IF EXISTS trg_order_metrics_item_costos_update ON ml_order_item_costos",
    "DROP TRIGGER IF EXISTS trg_order_metrics_item_costos_insert ON ml_order_item_costos",
    "DROP FUNCTION IF EXISTS order_metrics_enqueue_order_item_costos()",
    "DROP TRIGGER IF EXISTS trg_order_metrics_items_ops_delete ON ml_order_items_ops",
    "DROP TRIGGER IF EXISTS trg_order_metrics_items_ops_update ON ml_order_items_ops",
    "DROP TRIGGER IF EXISTS trg_order_metrics_items_ops_insert ON ml_order_items_ops",
    "DROP FUNCTION IF EXISTS order_metrics_enqueue_order_items_ops()",
    "DROP TRIGGER IF EXISTS trg_order_metrics_orders_ops_delete ON ml_orders_ops",
    "DROP TRIGGER IF EXISTS trg_order_metrics_orders_ops_update ON ml_orders_ops",
    "DROP TRIGGER IF EXISTS trg_order_metrics_orders_ops_insert ON ml_orders_ops",
    "DROP FUNCTION IF EXISTS order_metrics_enqueue_orders_ops()",
    "DROP FUNCTION IF EXISTS order_metrics_enqueue_system(BIGINT[], TEXT)",
    "DROP FUNCTION IF EXISTS order_metrics_enqueue(BIGINT[], TEXT)",
]


def upgrade() -> None:
    bind = op.get_bind()
    if bind.dialect.name != "postgresql":
        return
    for statement in _CREATE_STATEMENTS:
        op.execute(statement)


def downgrade() -> None:
    bind = op.get_bind()
    if bind.dialect.name != "postgresql":
        return
    for statement in _DROP_STATEMENTS:
        op.execute(statement)
