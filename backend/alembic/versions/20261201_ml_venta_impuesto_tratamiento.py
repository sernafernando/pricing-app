"""ml_venta_impuesto_tratamiento: which ML tax charges are informational, by period

Revision ID: 20261201_ml_venta_impuesto_tratamiento
Revises: 20261130_tb_item_full_row
Create Date: 2026-10-27

ventas-ml-impuestos-informativos S1, S2. One version per exact charge name
(`ml_payment_charges.name`) and start date: informational (shown, added back
into the neto, like SIRTAC) or deducted. Same date-range shape as
`ml_venta_varios_pct`. No row means the built-in rule, so existing metrics
do not change until someone configures a period.

The enqueue trigger re-queues the stored sales of the period that carry the
charge name. Its DDL is a FROZEN copy of
`app/services/order_metrics/triggers_tax_treatment.py` (migration
immutability contract, `triggers.py`); the module is never imported here.
"""

from typing import Sequence, Union

import sqlalchemy as sa
from alembic import op

revision: str = "20261201_ml_venta_impuesto_tratamiento"
down_revision: Union[str, None] = "20261130_tb_item_full_row"
branch_labels: Union[str, Sequence[str], None] = None
depends_on: Union[str, Sequence[str], None] = None


_TRIGGER_STATEMENTS = [
    """CREATE OR REPLACE FUNCTION order_metrics_enqueue_impuesto_tratamiento() RETURNS TRIGGER AS $trg$
DECLARE
    ids BIGINT[];
BEGIN
    IF TG_OP = 'DELETE' THEN

    SELECT COALESCE(array_agg(DISTINCT o.order_id), ARRAY[]::BIGINT[]) INTO ids
    FROM (SELECT charge_name, fecha_desde, fecha_hasta FROM old_table) r
    JOIN ml_payment_charges c ON c.name = r.charge_name
    JOIN ml_payments_ops p ON p.payment_id = c.payment_id
    JOIN ml_orders_ops o ON o.order_id = p.order_id
    WHERE o.date_created::date >= r.fecha_desde - 1
      AND (r.fecha_hasta IS NULL OR o.date_created::date <= r.fecha_hasta + 1);

        PERFORM order_metrics_enqueue(ids, 'impuesto_tratamiento_delete');
        RETURN NULL;
    END IF;

    IF TG_OP = 'INSERT' THEN

    SELECT COALESCE(array_agg(DISTINCT o.order_id), ARRAY[]::BIGINT[]) INTO ids
    FROM (SELECT charge_name, fecha_desde, fecha_hasta FROM new_table) r
    JOIN ml_payment_charges c ON c.name = r.charge_name
    JOIN ml_payments_ops p ON p.payment_id = c.payment_id
    JOIN ml_orders_ops o ON o.order_id = p.order_id
    WHERE o.date_created::date >= r.fecha_desde - 1
      AND (r.fecha_hasta IS NULL OR o.date_created::date <= r.fecha_hasta + 1);

        PERFORM order_metrics_enqueue(ids, 'impuesto_tratamiento_insert');
        RETURN NULL;
    END IF;

    -- UPDATE: only rows whose read columns changed, so an identical rewrite enqueues nothing.

    SELECT COALESCE(array_agg(DISTINCT o.order_id), ARRAY[]::BIGINT[]) INTO ids
    FROM (SELECT n.charge_name, n.fecha_desde, n.fecha_hasta FROM new_table n JOIN old_table od ON od.id = n.id WHERE 
        od.charge_name IS DISTINCT FROM n.charge_name
        OR od.informativo IS DISTINCT FROM n.informativo
        OR od.fecha_desde IS DISTINCT FROM n.fecha_desde
        OR od.fecha_hasta IS DISTINCT FROM n.fecha_hasta UNION SELECT od.charge_name, od.fecha_desde, od.fecha_hasta FROM old_table od JOIN new_table n ON n.id = od.id WHERE 
        od.charge_name IS DISTINCT FROM n.charge_name
        OR od.informativo IS DISTINCT FROM n.informativo
        OR od.fecha_desde IS DISTINCT FROM n.fecha_desde
        OR od.fecha_hasta IS DISTINCT FROM n.fecha_hasta) r
    JOIN ml_payment_charges c ON c.name = r.charge_name
    JOIN ml_payments_ops p ON p.payment_id = c.payment_id
    JOIN ml_orders_ops o ON o.order_id = p.order_id
    WHERE o.date_created::date >= r.fecha_desde - 1
      AND (r.fecha_hasta IS NULL OR o.date_created::date <= r.fecha_hasta + 1);

    PERFORM order_metrics_enqueue(ids, 'impuesto_tratamiento_update');
    RETURN NULL;
END;
$trg$ LANGUAGE plpgsql
""",
    "DROP TRIGGER IF EXISTS trg_order_metrics_impuesto_tratamiento_insert ON ml_venta_impuesto_tratamiento",
    """CREATE TRIGGER trg_order_metrics_impuesto_tratamiento_insert
AFTER INSERT ON ml_venta_impuesto_tratamiento
REFERENCING NEW TABLE AS new_table
FOR EACH STATEMENT EXECUTE FUNCTION order_metrics_enqueue_impuesto_tratamiento()
""",
    "DROP TRIGGER IF EXISTS trg_order_metrics_impuesto_tratamiento_update ON ml_venta_impuesto_tratamiento",
    """CREATE TRIGGER trg_order_metrics_impuesto_tratamiento_update
AFTER UPDATE ON ml_venta_impuesto_tratamiento
REFERENCING OLD TABLE AS old_table NEW TABLE AS new_table
FOR EACH STATEMENT EXECUTE FUNCTION order_metrics_enqueue_impuesto_tratamiento()
""",
    "DROP TRIGGER IF EXISTS trg_order_metrics_impuesto_tratamiento_delete ON ml_venta_impuesto_tratamiento",
    """CREATE TRIGGER trg_order_metrics_impuesto_tratamiento_delete
AFTER DELETE ON ml_venta_impuesto_tratamiento
REFERENCING OLD TABLE AS old_table
FOR EACH STATEMENT EXECUTE FUNCTION order_metrics_enqueue_impuesto_tratamiento()
""",
]

_DROP_TRIGGER_STATEMENTS = [
    "DROP TRIGGER IF EXISTS trg_order_metrics_impuesto_tratamiento_delete ON ml_venta_impuesto_tratamiento",
    "DROP TRIGGER IF EXISTS trg_order_metrics_impuesto_tratamiento_update ON ml_venta_impuesto_tratamiento",
    "DROP TRIGGER IF EXISTS trg_order_metrics_impuesto_tratamiento_insert ON ml_venta_impuesto_tratamiento",
    "DROP FUNCTION IF EXISTS order_metrics_enqueue_impuesto_tratamiento()",
]


def upgrade() -> None:
    op.create_table(
        "ml_venta_impuesto_tratamiento",
        sa.Column("id", sa.Integer(), primary_key=True),
        sa.Column("charge_name", sa.String(length=120), nullable=False),
        sa.Column("informativo", sa.Boolean(), nullable=False),
        sa.Column("fecha_desde", sa.Date(), nullable=False),
        sa.Column("fecha_hasta", sa.Date(), nullable=True),
        sa.Column("creado_por", sa.Integer(), sa.ForeignKey("usuarios.id"), nullable=True),
        sa.Column("created_at", sa.DateTime(timezone=True), server_default=sa.func.now(), nullable=False),
        sa.CheckConstraint(
            "fecha_hasta IS NULL OR fecha_hasta >= fecha_desde",
            name="ck_ml_venta_impuesto_tratamiento_fecha_rango",
        ),
        sa.UniqueConstraint("charge_name", "fecha_desde", name="uq_ml_venta_impuesto_tratamiento_nombre_desde"),
    )
    op.create_index("ix_ml_venta_impuesto_tratamiento_id", "ml_venta_impuesto_tratamiento", ["id"])
    op.create_index("ix_ml_venta_impuesto_tratamiento_charge_name", "ml_venta_impuesto_tratamiento", ["charge_name"])
    if op.get_bind().dialect.name != "postgresql":
        return
    for statement in _TRIGGER_STATEMENTS:
        op.execute(statement)


def downgrade() -> None:
    if op.get_bind().dialect.name == "postgresql":
        for statement in _DROP_TRIGGER_STATEMENTS:
            op.execute(statement)
    op.drop_index("ix_ml_venta_impuesto_tratamiento_charge_name", table_name="ml_venta_impuesto_tratamiento")
    op.drop_index("ix_ml_venta_impuesto_tratamiento_id", table_name="ml_venta_impuesto_tratamiento")
    op.drop_table("ml_venta_impuesto_tratamiento")
