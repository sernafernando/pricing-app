"""ml_payments_ops: a payment write recomputes every order sharing its shipment

Revision ID: 20261106_ml_payments_shipment_fanout
Revises: 20261105_sell_out_campanas
Create Date: 2026-10-20

flex-envio-comprador. The Flex buyer-paid shipping fallback of an order
(`envio_comprador.py`) is read only when NO payment of ANY order of its
shipment carries the shipping, so a sibling's payment write changes it. The
payments trigger used to enqueue only the payment's own order.

Minimal: only the body of `order_metrics_enqueue_payments_ops` changes
(`CREATE OR REPLACE FUNCTION`); the triggers that call it are untouched. No
table or column changes.

Frozen point-in-time copy of
`app/services/order_metrics/triggers_shipment_costs.py` (migration
immutability contract, `triggers.py`): the Python module is the LIVE
definition and is never re-imported here. Downgrade restores PR4's function
verbatim.
"""

from typing import Sequence, Union

from alembic import op

revision: str = "20261106_ml_payments_shipment_fanout"
down_revision: Union[str, None] = "20261105_sell_out_campanas"
branch_labels: Union[str, Sequence[str], None] = None
depends_on: Union[str, Sequence[str], None] = None


_UPGRADE_SQL = """
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
"""

_DOWNGRADE_SQL = """
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
$trg$ LANGUAGE plpgsql
"""


def upgrade() -> None:
    bind = op.get_bind()
    if bind.dialect.name != "postgresql":
        return
    op.execute(_UPGRADE_SQL)


def downgrade() -> None:
    bind = op.get_bind()
    if bind.dialect.name != "postgresql":
        return
    op.execute(_DOWNGRADE_SQL)
