"""A billing BFLX line landing recomputes the order's stored metrics
(ml-billing-balance PR 9-i-1).

The Flex "Bonificación por envío" (`bonificacion_flex.py`, from PR 9-i-2) reads the billing
BFLX line first and `raw_costs` only as a fallback. Billing lands days after the
sale and nothing recomputed the order when it did, so a sale computed from the
`raw_costs` fallback would keep that figure forever. Same pattern as
`triggers_shipment_costs.py`: in-transaction row triggers feeding the existing
dirty queue (no cron, no derived table).

Two triggers share one function:

- `AFTER INSERT ON ml_billing_charge_orders`: the bridge row that links a charge
  to an order is written right after the charge, so this is the moment a BFLX
  becomes visible to an order. `ON CONFLICT DO NOTHING` re-links fire nothing.
- `AFTER UPDATE OF amount, detail_sub_type ON ml_billing_charges`, only when the
  value changed: a re-sweep that corrects a BFLX amount recomputes its orders;
  an identical rewrite enqueues nothing (design D3 no-op rule).

Only BFLX charges enqueue. The enqueued set is every order of the charge's
linked orders AND of their shipments (the bonification is per shipment and
split among its orders). Orders absent from `ml_orders_ops` are skipped by the
join, so the queue's foreign key never fails.

Migration immutability contract (`triggers.py`): this module is the LIVE
definition for fixtures and future migrations; the migration
`20261020_ml_billing_flex_recompute_trigger.py` inlines its own FROZEN copy.
"""

from __future__ import annotations

from typing import List

from sqlalchemy.engine import Connection

_FUNCTION_SQL = """
CREATE OR REPLACE FUNCTION order_metrics_enqueue_billing_flex() RETURNS TRIGGER AS $trg$
DECLARE
    ids BIGINT[];
BEGIN
    IF NOT EXISTS (
        SELECT 1 FROM ml_billing_charges WHERE detail_id = NEW.detail_id AND detail_sub_type = 'BFLX'
    ) THEN
        RETURN NEW;
    END IF;
    SELECT COALESCE(array_agg(DISTINCT o.order_id), ARRAY[]::BIGINT[]) INTO ids
    FROM ml_billing_charge_orders l
    JOIN ml_orders_ops linked ON linked.order_id = l.order_id
    JOIN ml_orders_ops o ON o.order_id = linked.order_id
        OR (linked.shipping_id IS NOT NULL AND o.shipping_id = linked.shipping_id)
    WHERE l.detail_id = NEW.detail_id;
    PERFORM order_metrics_enqueue(ids, 'ml_billing_flex');
    RETURN NEW;
END;
$trg$ LANGUAGE plpgsql;
"""

_DROP_STATEMENTS: List[str] = [
    "DROP TRIGGER IF EXISTS trg_order_metrics_billing_flex_link ON ml_billing_charge_orders",
    "DROP TRIGGER IF EXISTS trg_order_metrics_billing_flex_charge ON ml_billing_charges",
    "DROP FUNCTION IF EXISTS order_metrics_enqueue_billing_flex()",
]

_CREATE_STATEMENTS: List[str] = [
    _FUNCTION_SQL,
    *_DROP_STATEMENTS[:2],
    """
CREATE TRIGGER trg_order_metrics_billing_flex_link
AFTER INSERT ON ml_billing_charge_orders
FOR EACH ROW EXECUTE FUNCTION order_metrics_enqueue_billing_flex()
""",
    """
CREATE TRIGGER trg_order_metrics_billing_flex_charge
AFTER UPDATE OF amount, detail_sub_type ON ml_billing_charges
FOR EACH ROW WHEN (
    OLD.amount IS DISTINCT FROM NEW.amount
    OR OLD.detail_sub_type IS DISTINCT FROM NEW.detail_sub_type
)
EXECUTE FUNCTION order_metrics_enqueue_billing_flex()
""",
]


def create_billing_flex_triggers(connection: Connection) -> None:
    """Idempotent: `CREATE OR REPLACE` the function, `DROP ... IF EXISTS` each
    trigger first. Needs `order_metrics_enqueue` (`create_triggers`) and both
    billing tables."""
    for statement in _CREATE_STATEMENTS:
        connection.exec_driver_sql(statement)


def drop_billing_flex_triggers(connection: Connection) -> None:
    for statement in _DROP_STATEMENTS:
        connection.exec_driver_sql(statement)
