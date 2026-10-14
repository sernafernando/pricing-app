"""ml_billing: drop the BFLX recompute triggers

Revision ID: 20261023_ml_billing_flex_drop_recompute_trigger
Revises: 20261022_usuarios_roles_adicionales
Create Date: 2026-10-23

Forward-only revert of `20261020_ml_billing_flex_recompute_trigger` (PR #1534).
That work was dropped: it added new triggers to the per-order metrics recompute
that Ventas ML relies on. The earlier migration may already have run, so it stays
untouched and this one removes what it created.

Upgrade drops both triggers and the function (`IF EXISTS`, so it is a no-op where
they were never created). Downgrade recreates them from a frozen copy of the
earlier migration's DDL; there is no live Python module for them anymore.
"""

from typing import Sequence, Union

from alembic import op

revision: str = "20261023_ml_billing_flex_drop_recompute_trigger"
down_revision: Union[str, None] = "20261022_usuarios_roles_adicionales"
branch_labels: Union[str, Sequence[str], None] = None
depends_on: Union[str, Sequence[str], None] = None

_DROP_STATEMENTS = [
    "DROP TRIGGER IF EXISTS trg_order_metrics_billing_flex_link ON ml_billing_charge_orders",
    "DROP TRIGGER IF EXISTS trg_order_metrics_billing_flex_charge ON ml_billing_charges",
    "DROP FUNCTION IF EXISTS order_metrics_enqueue_billing_flex()",
]

_RECREATE_STATEMENTS = [
    """
CREATE OR REPLACE FUNCTION order_metrics_enqueue_billing_flex() RETURNS TRIGGER AS $trg$
DECLARE
    ids BIGINT[];
    src_detail TEXT;
    src_order BIGINT := NULL;
    touches_bflx BOOLEAN;
BEGIN
    IF TG_TABLE_NAME = 'ml_billing_charge_orders' THEN
        -- A link written or removed only concerns ITS order (and that order's
        -- shipment siblings), not the charge's other links.
        IF TG_OP = 'DELETE' THEN
            src_detail := OLD.detail_id;
            src_order := OLD.order_id;
        ELSE
            src_detail := NEW.detail_id;
            src_order := NEW.order_id;
        END IF;
        touches_bflx := EXISTS (
            SELECT 1 FROM ml_billing_charges WHERE detail_id = src_detail AND detail_sub_type = 'BFLX'
        );
    ELSE
        -- A charge that STOPS being BFLX changes its orders just like one that becomes it.
        src_detail := NEW.detail_id;
        touches_bflx := NEW.detail_sub_type = 'BFLX' OR OLD.detail_sub_type = 'BFLX';
    END IF;
    IF NOT touches_bflx THEN
        RETURN NULL;
    END IF;
    SELECT COALESCE(array_agg(DISTINCT o.order_id), ARRAY[]::BIGINT[]) INTO ids
    FROM ml_orders_ops linked
    JOIN ml_orders_ops o ON o.order_id = linked.order_id
        OR (linked.shipping_id IS NOT NULL AND o.shipping_id = linked.shipping_id)
    WHERE linked.order_id = src_order
        OR (src_order IS NULL AND linked.order_id IN (
            SELECT order_id FROM ml_billing_charge_orders WHERE detail_id = src_detail
        ));
    PERFORM order_metrics_enqueue(ids, 'ml_billing_flex');
    RETURN NULL;
END;
$trg$ LANGUAGE plpgsql;
""",
    *_DROP_STATEMENTS[:2],
    """
CREATE TRIGGER trg_order_metrics_billing_flex_link
AFTER INSERT OR DELETE ON ml_billing_charge_orders
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
    for statement in _DROP_STATEMENTS:
        op.execute(statement)


def downgrade() -> None:
    bind = op.get_bind()
    if bind.dialect.name != "postgresql":
        return
    for statement in _RECREATE_STATEMENTS:
        op.execute(statement)
