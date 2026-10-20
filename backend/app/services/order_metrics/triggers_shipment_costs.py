"""`raw_costs` joins the shipment trigger's watched columns
(ventas-ml-bonificacion-envio-flex).

`triggers.py` (PR4) deliberately left `raw_costs` out: "sender_cost/
receiver_cost/raw_costs stay trigger-free". That was right while nothing in
the metrics formula read it. The Flex "Bonificación por envío"
(`bonificacion_flex.py`) reads `raw_costs.senders[].discounts` and
`raw_costs.receiver.discounts`, and the cost
payload lands AFTER the shipment (`sweep_service._sync_shipment_costs`
fetches it on a later pass) -- so a sale computed before it arrived would
keep its stale Total Gauss forever without this.

Only the UPDATE trigger changes; its function
(`order_metrics_enqueue_shipments_ops`, which fans out to EVERY order
sharing the shipment) is reused as is. `sender_cost`/`receiver_cost` stay
unwatched: no formula reads them. The `WHEN` guard keeps the no-op rule of
design D3 rev 5 -- the sweep re-stores the payload on every retry, and an
identical rewrite (`IS DISTINCT FROM` on jsonb) enqueues nothing.

flex-envio-comprador: the Flex buyer-paid shipping fallback
(`envio_comprador.py`) of an order is read only when NO payment of ANY order
of its shipment carries the shipping. So a payment write must also recompute
every order sharing the payment's shipment, not only the payment's own order:
`order_metrics_enqueue_payments_ops` is replaced (`CREATE OR REPLACE
FUNCTION`, idempotent) with a body that adds those siblings. The trigger
itself (`triggers.py`) is untouched.

Migration immutability contract (`triggers.py`): this module is the LIVE
definition for fixtures and future migrations; the migrations
`20261008_ml_shipments_raw_costs_trigger.py` and
`20261106_ml_payments_shipment_fanout.py` inline their own FROZEN copies and
are never re-synced. `triggers.py`'s own statements stay untouched.
"""

from __future__ import annotations

from typing import List

from sqlalchemy.engine import Connection

_CREATE_STATEMENTS: List[str] = [
    "DROP TRIGGER IF EXISTS trg_order_metrics_shipments_ops_update ON ml_shipments_ops",
    """
CREATE TRIGGER trg_order_metrics_shipments_ops_update
AFTER UPDATE OF logistic_type, receiver_address, raw_costs ON ml_shipments_ops
FOR EACH ROW WHEN (
    OLD.logistic_type IS DISTINCT FROM NEW.logistic_type
    OR OLD.receiver_address IS DISTINCT FROM NEW.receiver_address
    OR OLD.raw_costs IS DISTINCT FROM NEW.raw_costs
)
EXECUTE FUNCTION order_metrics_enqueue_shipments_ops()
""",
    """
CREATE OR REPLACE FUNCTION order_metrics_enqueue_payments_ops() RETURNS TRIGGER AS $trg$
DECLARE
    ids BIGINT[];
BEGIN
    IF TG_OP = 'DELETE' THEN
        ids := ARRAY[OLD.order_id];
    ELSIF TG_OP = 'UPDATE' AND OLD.order_id IS DISTINCT FROM NEW.order_id THEN
        ids := ARRAY[OLD.order_id, NEW.order_id];
    ELSE
        ids := ARRAY[NEW.order_id];
    END IF;
    -- Every order sharing the shipment of those orders (flex-envio-comprador).
    -- The self-join also returns the payment's own order(s): DISTINCT keeps
    -- each id once, so the enqueue never sees a duplicate.
    ids := ARRAY(
        SELECT DISTINCT x FROM unnest(ids || ARRAY(
            SELECT sibling.order_id
            FROM ml_orders_ops AS own
            JOIN ml_orders_ops AS sibling ON sibling.shipping_id = own.shipping_id
            WHERE own.order_id = ANY(ids) AND own.shipping_id IS NOT NULL
        )) AS x
    );
    PERFORM order_metrics_enqueue(
        ids,
        CASE
            WHEN TG_OP = 'DELETE' THEN 'ml_payments_ops_delete'
            WHEN TG_OP = 'INSERT' THEN 'ml_payments_ops_insert'
            ELSE 'ml_payments_ops_update'
        END
    );
    IF TG_OP = 'DELETE' THEN
        RETURN OLD;
    END IF;
    RETURN NEW;
END;
$trg$ LANGUAGE plpgsql
""",
]


def create_shipment_costs_trigger(connection: Connection) -> None:
    """Replaces PR4's shipment UPDATE trigger with one that also watches
    `raw_costs`, and the payments function with one that fans out to the
    orders sharing the shipment. Must run AFTER `create_triggers` (which
    defines both functions and the original trigger). Idempotent: `DROP ...
    IF EXISTS` first, so re-applying never collides on `CREATE TRIGGER`."""
    for statement in _CREATE_STATEMENTS:
        connection.exec_driver_sql(statement)
