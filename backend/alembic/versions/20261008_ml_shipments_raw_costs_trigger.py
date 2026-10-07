"""ml_shipments_ops: recompute the stored metrics when `raw_costs` changes

Revision ID: 20261008_ml_shipments_raw_costs_trigger
Revises: 20261007_ml_items_seller_sku_vendido
Create Date: 2026-10-08

ventas-ml-bonificacion-envio-flex. The Flex "Bonificación por envío" is read
from `ml_shipments_ops.raw_costs` (`receiver.discounts`), and that payload
lands after the shipment row. Until now `raw_costs` was deliberately not
watched, so a sale computed before its costs arrived kept a stale Total
Gauss forever.

Frozen point-in-time copy of
`app/services/order_metrics/triggers_shipment_costs.py` (migration
immutability contract, `triggers.py`): the Python module is the LIVE
definition and is never re-imported here.

Replaces only the UPDATE trigger; its function
(`order_metrics_enqueue_shipments_ops`) already fans out to every order
sharing the shipment. Downgrade restores PR4's trigger verbatim.
"""

from typing import Sequence, Union

from alembic import op

revision: str = "20261008_ml_shipments_raw_costs_trigger"
down_revision: Union[str, None] = "20261007_ml_items_seller_sku_vendido"
branch_labels: Union[str, Sequence[str], None] = None
depends_on: Union[str, Sequence[str], None] = None


_UPGRADE_STATEMENTS = [
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

_DOWNGRADE_STATEMENTS = [
    "DROP TRIGGER IF EXISTS trg_order_metrics_shipments_ops_update ON ml_shipments_ops",
    """
CREATE TRIGGER trg_order_metrics_shipments_ops_update
AFTER UPDATE OF logistic_type, receiver_address ON ml_shipments_ops
FOR EACH ROW WHEN (
    OLD.logistic_type IS DISTINCT FROM NEW.logistic_type
    OR OLD.receiver_address IS DISTINCT FROM NEW.receiver_address
)
EXECUTE FUNCTION order_metrics_enqueue_shipments_ops()
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
    for statement in _DOWNGRADE_STATEMENTS:
        op.execute(statement)
