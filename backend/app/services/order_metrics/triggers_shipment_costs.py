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

Migration immutability contract (`triggers.py`): this module is the LIVE
definition for fixtures and future migrations; the migration
`20261008_ml_shipments_raw_costs_trigger.py` inlines its own FROZEN copy and
is never re-synced. `triggers.py`'s own statements stay untouched.
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
]


def create_shipment_costs_trigger(connection: Connection) -> None:
    """Replaces PR4's shipment UPDATE trigger with one that also watches
    `raw_costs`. Must run AFTER `create_triggers` (which defines the
    function and the original trigger). Idempotent: `DROP ... IF EXISTS`
    first, so re-applying never collides on `CREATE TRIGGER`."""
    for statement in _CREATE_STATEMENTS:
        connection.exec_driver_sql(statement)
