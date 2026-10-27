"""Enqueue trigger for `ml_venta_impuesto_tratamiento` (ventas-ml-impuestos-informativos S2).

`breakdown_service.informational_rule` reads the version of one charge name in force at the sale's `date_created`,
so the affected orders are those whose date falls in the OLD or NEW `[fecha_desde, fecha_hasta]` window of a touched
row (both sides: narrowing a window must recompute the orders that just left it) AND whose payments carry that
exact charge name. Inclusive on both ends, like `% de varios` (`triggers_config.py`): over-enqueueing at the
boundary is harmless, missing it is not.

Migration immutability contract (`triggers.py`): this module is the LIVE definition for fixtures and future
migrations; `20261201_ml_venta_impuesto_tratamiento.py` inlines its own FROZEN copy.
"""

from __future__ import annotations

from typing import List

from sqlalchemy.engine import Connection

# The orders a set of (charge_name, fecha_desde, fecha_hasta) ranges `r` covers.
_ORDERS_IN_RANGES = """
    SELECT COALESCE(array_agg(DISTINCT o.order_id), ARRAY[]::BIGINT[]) INTO ids
    FROM ({ranges}) r
    JOIN ml_payment_charges c ON c.name = r.charge_name
    JOIN ml_payments_ops p ON p.payment_id = c.payment_id
    JOIN ml_orders_ops o ON o.order_id = p.order_id
    WHERE o.date_created::date >= r.fecha_desde
      AND (r.fecha_hasta IS NULL OR o.date_created::date <= r.fecha_hasta);
"""

_CHANGED = """
        od.charge_name IS DISTINCT FROM n.charge_name
        OR od.informativo IS DISTINCT FROM n.informativo
        OR od.fecha_desde IS DISTINCT FROM n.fecha_desde
        OR od.fecha_hasta IS DISTINCT FROM n.fecha_hasta"""

_FUNCTION_SQL = f"""
CREATE OR REPLACE FUNCTION order_metrics_enqueue_impuesto_tratamiento() RETURNS TRIGGER AS $trg$
DECLARE
    ids BIGINT[];
BEGIN
    IF TG_OP = 'DELETE' THEN
{_ORDERS_IN_RANGES.format(ranges="SELECT charge_name, fecha_desde, fecha_hasta FROM old_table")}
        PERFORM order_metrics_enqueue(ids, 'impuesto_tratamiento_delete');
        RETURN NULL;
    END IF;

    IF TG_OP = 'INSERT' THEN
{_ORDERS_IN_RANGES.format(ranges="SELECT charge_name, fecha_desde, fecha_hasta FROM new_table")}
        PERFORM order_metrics_enqueue(ids, 'impuesto_tratamiento_insert');
        RETURN NULL;
    END IF;

    -- UPDATE: only rows whose read columns changed, so an identical rewrite enqueues nothing.
{
    _ORDERS_IN_RANGES.format(
        ranges=(
            "SELECT n.charge_name, n.fecha_desde, n.fecha_hasta FROM new_table n JOIN old_table od ON od.id = n.id"
            f" WHERE {_CHANGED}"
            " UNION SELECT od.charge_name, od.fecha_desde, od.fecha_hasta FROM old_table od"
            f" JOIN new_table n ON n.id = od.id WHERE {_CHANGED}"
        )
    )
}
    PERFORM order_metrics_enqueue(ids, 'impuesto_tratamiento_update');
    RETURN NULL;
END;
$trg$ LANGUAGE plpgsql
"""

_CREATE_STATEMENTS: List[str] = [
    _FUNCTION_SQL,
    # One trigger per event: Postgres forbids transition tables on a multi-event trigger.
    "DROP TRIGGER IF EXISTS trg_order_metrics_impuesto_tratamiento_insert ON ml_venta_impuesto_tratamiento",
    """
CREATE TRIGGER trg_order_metrics_impuesto_tratamiento_insert
AFTER INSERT ON ml_venta_impuesto_tratamiento
REFERENCING NEW TABLE AS new_table
FOR EACH STATEMENT EXECUTE FUNCTION order_metrics_enqueue_impuesto_tratamiento()
""",
    "DROP TRIGGER IF EXISTS trg_order_metrics_impuesto_tratamiento_update ON ml_venta_impuesto_tratamiento",
    """
CREATE TRIGGER trg_order_metrics_impuesto_tratamiento_update
AFTER UPDATE ON ml_venta_impuesto_tratamiento
REFERENCING OLD TABLE AS old_table NEW TABLE AS new_table
FOR EACH STATEMENT EXECUTE FUNCTION order_metrics_enqueue_impuesto_tratamiento()
""",
    "DROP TRIGGER IF EXISTS trg_order_metrics_impuesto_tratamiento_delete ON ml_venta_impuesto_tratamiento",
    """
CREATE TRIGGER trg_order_metrics_impuesto_tratamiento_delete
AFTER DELETE ON ml_venta_impuesto_tratamiento
REFERENCING OLD TABLE AS old_table
FOR EACH STATEMENT EXECUTE FUNCTION order_metrics_enqueue_impuesto_tratamiento()
""",
]

_DROP_STATEMENTS: List[str] = [
    "DROP TRIGGER IF EXISTS trg_order_metrics_impuesto_tratamiento_delete ON ml_venta_impuesto_tratamiento",
    "DROP TRIGGER IF EXISTS trg_order_metrics_impuesto_tratamiento_update ON ml_venta_impuesto_tratamiento",
    "DROP TRIGGER IF EXISTS trg_order_metrics_impuesto_tratamiento_insert ON ml_venta_impuesto_tratamiento",
    "DROP FUNCTION IF EXISTS order_metrics_enqueue_impuesto_tratamiento()",
]


def create_tax_treatment_triggers(connection: Connection) -> None:
    """Applies the enqueue function and its three statement triggers. Postgres-only; requires
    `order_metrics_enqueue` (`triggers.py`). Idempotent: each trigger is dropped first."""
    for statement in _CREATE_STATEMENTS:
        connection.exec_driver_sql(statement)


def drop_tax_treatment_triggers(connection: Connection) -> None:
    """Reverse of `create_tax_treatment_triggers`."""
    for statement in _DROP_STATEMENTS:
        connection.exec_driver_sql(statement)
