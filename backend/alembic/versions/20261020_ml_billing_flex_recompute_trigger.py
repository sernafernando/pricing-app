"""ml_billing: recompute the stored metrics when a BFLX line lands

Revision ID: 20261020_ml_billing_flex_recompute_trigger
Revises: 20261019_admin_limpieza_masiva_grant
Create Date: 2026-10-20

ml-billing-balance PR 9-i-1. The Flex "Bonificacion por envio" reads (from 9-i-2) the
billing BFLX line first (`bonificacion_flex.py`), and billing lands after the
sale. These triggers put the affected orders (and their shipment siblings) on
the existing dirty queue the moment the BFLX is linked or its amount changes.

Frozen point-in-time copy of `app/services/order_metrics/triggers_billing_flex.py`
(migration immutability contract, `triggers.py`): the Python module is the LIVE
definition and is never re-imported here. Downgrade drops both triggers and the
function.
"""

from typing import Sequence, Union

from alembic import op

revision: str = "20261020_ml_billing_flex_recompute_trigger"
down_revision: Union[str, None] = "20261019_admin_limpieza_masiva_grant"
branch_labels: Union[str, Sequence[str], None] = None
depends_on: Union[str, Sequence[str], None] = None

_DROP_STATEMENTS = [
    "DROP TRIGGER IF EXISTS trg_order_metrics_billing_flex_link ON ml_billing_charge_orders",
    "DROP TRIGGER IF EXISTS trg_order_metrics_billing_flex_charge ON ml_billing_charges",
    "DROP FUNCTION IF EXISTS order_metrics_enqueue_billing_flex()",
]

_UPGRADE_STATEMENTS = [
    """
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
""",
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


def upgrade() -> None:
    bind = op.get_bind()
    if bind.dialect.name != "postgresql":
        return
    for statement in _UPGRADE_STATEMENTS:
        op.execute(statement)


def downgrade() -> None:
    bind = op.get_bind()
    if bind.dialect.name != "postgresql":
        return
    for statement in _DROP_STATEMENTS:
        op.execute(statement)
