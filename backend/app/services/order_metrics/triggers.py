"""Enqueue functions + per-order row-level triggers (ventas-ml-rediseno PR4,
design D3, D7, D8). Postgres-only DDL, applied EXPLICITLY by the Alembic
migration and by the dedicated `pg_order_metrics_triggers_engine` test
fixture (`tests/conftest.py`) -- never by a global SQLAlchemy metadata
event.

Deviation from the design's literal "applied ... by an after_create
listener" (D3/D7/D8): `MlOrderMetricsDirty.__table__` is SHARED by several
PRE-EXISTING PR1/PR3 fixtures (`pg_order_metrics_engine`, `pg_worker_engine`)
that create it WITHOUT the six sibling input tables this DDL references --
a global `after_create` listener on that table fired for every one of them
too and broke with `UndefinedTable: ml_shipments_ops` the moment this PR's
fixture and the pre-existing ones coexisted in the same test session. Direct
calls from the exact fixture (and the migration) that own the six input
tables are the only thing safe to fire unconditionally; SQLite
`create_all` never calls either of these (design D8's own guarantee still
holds).

Two enqueue helpers, DIFFERENT conflict semantics (design D3 rev 3):
- `order_metrics_enqueue(ids, reason)` -- the ONLY one called by triggers
  below. Bumps `version`, resets `attempts`/`last_error`/`suspect` (a new
  input write is a new chance -- un-parks a poisoned order), never touches
  the claim columns (an in-flight claim stays owned; the version bump alone
  forces that worker's release to leave the row dirty -- D5 fence).
- `order_metrics_enqueue_system(ids, reason)` -- reconcile/divergence only
  (PR6), `ON CONFLICT DO NOTHING`: never un-parks, never bumps version.

Both fold every `pg_notify('order_metrics_dirty', '')` call inside one
transaction into ONE delivery (Postgres's own NOTIFY semantics -- no extra
code needed) and only deliver on COMMIT, never on ROLLBACK (design D3).

No-op writes never enqueue (design D3 rev 5): every UPDATE trigger below
carries a `WHEN (... IS DISTINCT FROM ...)` guard over exactly the columns
`compute_order_metrics`'s formula chain reads from that table, so a sweep
that re-upserts identical values -- or un-parks nothing -- enqueues nothing.

Postgres trigger restrictions (design D3 rev 7): every trigger here is
ROW-level, so `UPDATE OF <cols>` plus a row-level `WHEN` clause is valid
(the transition-table / no-column-list restriction applies only to the
STATEMENT-level config triggers PR5 ships).
"""

from __future__ import annotations

from typing import List

from sqlalchemy.engine import Connection

# Tables `compute_order_metrics` (PR1.T6/D7) actually reads THAT HAVE A
# PER-ORDER ROW TRIGGER as of this PR. PR4.T10/T11's read-set guard fails
# the moment `compute_order_metrics` starts reading a table missing here --
# see `app/services/order_metrics/read_set_guard.py`. PR5 extends this set
# with the config/statement-level tables (varios_venta_pct,
# logistica_costo_cordon, codigos_postales, configuracion, transportes,
# etiquetas_envio); they are NOT triggered yet, on purpose, in this PR.
TRIGGERED_TABLES = frozenset(
    {
        "ml_orders_ops",
        "ml_order_items_ops",
        "ml_order_item_costos",
        "ml_payments_ops",
        "ml_payment_charges",
        "ml_shipments_ops",
    }
)


_ENQUEUE_FUNCTIONS_SQL = """
CREATE OR REPLACE FUNCTION order_metrics_enqueue(ids BIGINT[], reason TEXT)
RETURNS VOID AS $order_metrics_enqueue$
BEGIN
    IF ids IS NULL OR array_length(ids, 1) IS NULL THEN
        RETURN;
    END IF;
    INSERT INTO ml_order_metrics_dirty (order_id, version, reason, enqueued_at, attempts, last_error, suspect)
    SELECT DISTINCT x, 1, reason, now(), 0, NULL, false FROM unnest(ids) AS x
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
CREATE OR REPLACE FUNCTION order_metrics_enqueue_payment_charges() RETURNS TRIGGER AS $trg$
DECLARE
    resolved_order_id BIGINT;
BEGIN
    IF TG_OP = 'DELETE' THEN
        SELECT order_id INTO resolved_order_id FROM ml_payments_ops WHERE payment_id = OLD.payment_id;
        IF resolved_order_id IS NOT NULL THEN
            PERFORM order_metrics_enqueue(ARRAY[resolved_order_id], 'ml_payment_charges_delete');
        END IF;
        RETURN OLD;
    END IF;
    SELECT order_id INTO resolved_order_id FROM ml_payments_ops WHERE payment_id = NEW.payment_id;
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
AFTER UPDATE OF amount, refunded, type, name ON ml_payment_charges
FOR EACH ROW WHEN (
    OLD.amount IS DISTINCT FROM NEW.amount
    OR OLD.refunded IS DISTINCT FROM NEW.refunded
    OR OLD.type IS DISTINCT FROM NEW.type
    OR OLD.name IS DISTINCT FROM NEW.name
)
EXECUTE FUNCTION order_metrics_enqueue_payment_charges();

CREATE TRIGGER trg_order_metrics_payment_charges_delete
AFTER DELETE ON ml_payment_charges
FOR EACH ROW EXECUTE FUNCTION order_metrics_enqueue_payment_charges();
"""

_SHIPMENTS_OPS_TRIGGER_SQL = """
CREATE OR REPLACE FUNCTION order_metrics_enqueue_shipments_ops() RETURNS TRIGGER AS $trg$
BEGIN
    IF NEW.order_id IS NOT NULL THEN
        PERFORM order_metrics_enqueue(ARRAY[NEW.order_id], 'ml_shipments_ops_update');
    END IF;
    RETURN NEW;
END;
$trg$ LANGUAGE plpgsql;

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
"""

# Order matters: functions before the triggers that call them; each table's
# own function before its own triggers.
_CREATE_STATEMENTS: List[str] = [
    _ENQUEUE_FUNCTIONS_SQL,
    _ENQUEUE_SYSTEM_FUNCTION_SQL,
    _ORDERS_OPS_TRIGGER_SQL,
    _ORDER_ITEMS_OPS_TRIGGER_SQL,
    _ORDER_ITEM_COSTOS_TRIGGER_SQL,
    _PAYMENTS_OPS_TRIGGER_SQL,
    _PAYMENT_CHARGES_TRIGGER_SQL,
    _SHIPMENTS_OPS_TRIGGER_SQL,
]

_DROP_STATEMENTS: List[str] = [
    "DROP TRIGGER IF EXISTS trg_order_metrics_shipments_ops_update ON ml_shipments_ops",
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


def create_triggers(bind: Connection) -> None:
    """Applies every enqueue function + row trigger, in dependency order.
    Postgres-only -- callers (the Alembic migration, and the
    `after_create` listener below) never call this under SQLite."""
    for statement in _CREATE_STATEMENTS:
        bind.exec_driver_sql(statement)


def drop_triggers(bind: Connection) -> None:
    """Reverse of `create_triggers`: triggers before the functions they
    call, so nothing is ever left referencing an already-dropped function."""
    for statement in _DROP_STATEMENTS:
        bind.exec_driver_sql(statement)
