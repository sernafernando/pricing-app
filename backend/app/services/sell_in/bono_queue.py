"""The `sell_in_bono_dirty` queue (sell-in-sell-out T3c-3): which brand bonuses
and Compras operations must have their generated sell ins reconciled. No cron:
row triggers queue a key and `pg_notify('sell_in_bono_dirty')`.

Every trigger is GATED on an active bonus, so nothing is queued while no bonus
exists (and a key is only queued when some active bonus can care about it):

- `sell_in_bonos_marca`: an INSERT of an active bonus, or an UPDATE that changes
  what it pays (brand, amount, currency, range, estado, author) while it is or
  was active (a void is queued: what it generated must be voided);
- `pedidos_compra`: an UPDATE of `fecha_factura`, `estado`, `tipo_cambio` or
  `proveedor_id` that changes it, and an INSERT or DELETE, queue the operation
  when its old or new invoice date falls in an active bonus's range;
- `pedido_compra_lineas_facturadas` (invoiced units): an INSERT or DELETE, or an
  UPDATE that changes `pedido_id`, `item_id` or `cantidad`, queue the operation
  under the same date rule (a line deleted by its operation's cascade is
  covered by the operation's own DELETE);
- `productos_erp`: a new product, or one whose `marca` changes, queues the
  operations invoicing it when an active bonus of its old or new brand covers
  their invoice date.

The gate is `sell_in_bono_cubre(fecha[, marca])`: one indexed EXISTS over the
(few) bonuses. A trigger does no reconcile work. `UPGRADE_SQL`/`DOWNGRADE_SQL`
are the live definition; the migration `20261107_sell_in_bonos_marca` carries a
frozen copy and owns the table (`app.models.sell_in.SellInBonoDirty`).
"""

from __future__ import annotations

from typing import List

CHANNEL = "sell_in_bono_dirty"

_UPSERT = (
    "INSERT INTO sell_in_bono_dirty (tipo, ref) VALUES ({tipo}, {ref}) "
    "ON CONFLICT (tipo, ref) DO UPDATE SET enqueued_at = now(), attempts = 0, last_error = NULL"
)

UPGRADE_SQL: List[str] = [
    """
CREATE OR REPLACE FUNCTION sell_in_bono_cubre(p_fecha DATE, p_marca TEXT DEFAULT NULL) RETURNS BOOLEAN AS $fn$
    SELECT p_fecha IS NOT NULL AND EXISTS (
        SELECT 1 FROM sell_in_bonos_marca AS b
        WHERE b.estado = 'activa' AND p_fecha BETWEEN b.fecha_desde AND b.fecha_hasta
          AND (p_marca IS NULL OR b.marca = p_marca)
    )
$fn$ LANGUAGE sql STABLE
""",
    f"""
CREATE OR REPLACE FUNCTION sell_in_bono_enqueue_bono() RETURNS TRIGGER AS $trg$
BEGIN
    IF NEW.estado = 'activa' OR (TG_OP = 'UPDATE' AND OLD.estado = 'activa') THEN
        {_UPSERT.format(tipo="'bono'", ref="NEW.id")};
        PERFORM pg_notify('{CHANNEL}', '');
    END IF;
    RETURN NULL;
END;
$trg$ LANGUAGE plpgsql
""",
    f"""
CREATE OR REPLACE FUNCTION sell_in_bono_enqueue_pedido() RETURNS TRIGGER AS $trg$
DECLARE
    encolado BOOLEAN := false;
BEGIN
    IF TG_OP <> 'INSERT' AND sell_in_bono_cubre(OLD.fecha_factura) THEN
        {_UPSERT.format(tipo="'pedido'", ref="OLD.id")};
        encolado := true;
    END IF;
    IF TG_OP <> 'DELETE' AND sell_in_bono_cubre(NEW.fecha_factura) THEN
        {_UPSERT.format(tipo="'pedido'", ref="NEW.id")};
        encolado := true;
    END IF;
    IF encolado THEN
        PERFORM pg_notify('{CHANNEL}', '');
    END IF;
    RETURN NULL;
END;
$trg$ LANGUAGE plpgsql
""",
    f"""
CREATE OR REPLACE FUNCTION sell_in_bono_enqueue_linea() RETURNS TRIGGER AS $trg$
DECLARE
    pedidos BIGINT[];
BEGIN
    IF TG_OP = 'INSERT' THEN
        pedidos := ARRAY[NEW.pedido_id];
    ELSIF TG_OP = 'DELETE' THEN
        pedidos := ARRAY[OLD.pedido_id];
    ELSE
        pedidos := ARRAY[OLD.pedido_id, NEW.pedido_id];
    END IF;
    INSERT INTO sell_in_bono_dirty (tipo, ref)
    SELECT DISTINCT 'pedido', p.id FROM pedidos_compra AS p
    WHERE p.id = ANY(pedidos) AND sell_in_bono_cubre(p.fecha_factura)
    ORDER BY 2
    ON CONFLICT (tipo, ref) DO UPDATE SET enqueued_at = now(), attempts = 0, last_error = NULL;
    IF FOUND THEN
        PERFORM pg_notify('{CHANNEL}', '');
    END IF;
    RETURN NULL;
END;
$trg$ LANGUAGE plpgsql
""",
    f"""
CREATE OR REPLACE FUNCTION sell_in_bono_enqueue_producto() RETURNS TRIGGER AS $trg$
BEGIN
    INSERT INTO sell_in_bono_dirty (tipo, ref)
    SELECT DISTINCT 'pedido', l.pedido_id
    FROM pedido_compra_lineas_facturadas AS l
    JOIN pedidos_compra AS p ON p.id = l.pedido_id
    WHERE l.item_id = NEW.item_id
      AND (sell_in_bono_cubre(p.fecha_factura, NEW.marca)
           OR (TG_OP = 'UPDATE' AND sell_in_bono_cubre(p.fecha_factura, OLD.marca)))
    ORDER BY 2
    ON CONFLICT (tipo, ref) DO UPDATE SET enqueued_at = now(), attempts = 0, last_error = NULL;
    IF FOUND THEN
        PERFORM pg_notify('{CHANNEL}', '');
    END IF;
    RETURN NULL;
END;
$trg$ LANGUAGE plpgsql
""",
    """
CREATE TRIGGER trg_sell_in_bono_bonos_insert
AFTER INSERT ON sell_in_bonos_marca
FOR EACH ROW EXECUTE FUNCTION sell_in_bono_enqueue_bono()
""",
    """
CREATE TRIGGER trg_sell_in_bono_bonos_update
AFTER UPDATE ON sell_in_bonos_marca
FOR EACH ROW WHEN (
    (OLD.marca, OLD.monto_unit, OLD.moneda, OLD.fecha_desde, OLD.fecha_hasta, OLD.estado, OLD.usuario_id)
    IS DISTINCT FROM
    (NEW.marca, NEW.monto_unit, NEW.moneda, NEW.fecha_desde, NEW.fecha_hasta, NEW.estado, NEW.usuario_id)
)
EXECUTE FUNCTION sell_in_bono_enqueue_bono()
""",
    """
CREATE TRIGGER trg_sell_in_bono_pedidos_insert_delete
AFTER INSERT OR DELETE ON pedidos_compra
FOR EACH ROW EXECUTE FUNCTION sell_in_bono_enqueue_pedido()
""",
    """
CREATE TRIGGER trg_sell_in_bono_pedidos_update
AFTER UPDATE OF fecha_factura, estado, tipo_cambio, proveedor_id ON pedidos_compra
FOR EACH ROW WHEN (
    (OLD.fecha_factura, OLD.estado, OLD.tipo_cambio, OLD.proveedor_id)
    IS DISTINCT FROM (NEW.fecha_factura, NEW.estado, NEW.tipo_cambio, NEW.proveedor_id)
)
EXECUTE FUNCTION sell_in_bono_enqueue_pedido()
""",
    """
CREATE TRIGGER trg_sell_in_bono_lineas_insert_delete
AFTER INSERT OR DELETE ON pedido_compra_lineas_facturadas
FOR EACH ROW EXECUTE FUNCTION sell_in_bono_enqueue_linea()
""",
    """
CREATE TRIGGER trg_sell_in_bono_lineas_update
AFTER UPDATE OF pedido_id, item_id, cantidad ON pedido_compra_lineas_facturadas
FOR EACH ROW WHEN ((OLD.pedido_id, OLD.item_id, OLD.cantidad) IS DISTINCT FROM (NEW.pedido_id, NEW.item_id, NEW.cantidad))
EXECUTE FUNCTION sell_in_bono_enqueue_linea()
""",
    """
CREATE TRIGGER trg_sell_in_bono_productos_insert
AFTER INSERT ON productos_erp
FOR EACH ROW EXECUTE FUNCTION sell_in_bono_enqueue_producto()
""",
    """
CREATE TRIGGER trg_sell_in_bono_productos_marca
AFTER UPDATE OF marca ON productos_erp
FOR EACH ROW WHEN (OLD.marca IS DISTINCT FROM NEW.marca)
EXECUTE FUNCTION sell_in_bono_enqueue_producto()
""",
]

DOWNGRADE_SQL: List[str] = [
    "DROP TRIGGER IF EXISTS trg_sell_in_bono_productos_marca ON productos_erp",
    "DROP TRIGGER IF EXISTS trg_sell_in_bono_productos_insert ON productos_erp",
    "DROP TRIGGER IF EXISTS trg_sell_in_bono_lineas_update ON pedido_compra_lineas_facturadas",
    "DROP TRIGGER IF EXISTS trg_sell_in_bono_lineas_insert_delete ON pedido_compra_lineas_facturadas",
    "DROP TRIGGER IF EXISTS trg_sell_in_bono_pedidos_update ON pedidos_compra",
    "DROP TRIGGER IF EXISTS trg_sell_in_bono_pedidos_insert_delete ON pedidos_compra",
    "DROP TRIGGER IF EXISTS trg_sell_in_bono_bonos_update ON sell_in_bonos_marca",
    "DROP TRIGGER IF EXISTS trg_sell_in_bono_bonos_insert ON sell_in_bonos_marca",
    "DROP FUNCTION IF EXISTS sell_in_bono_enqueue_producto()",
    "DROP FUNCTION IF EXISTS sell_in_bono_enqueue_linea()",
    "DROP FUNCTION IF EXISTS sell_in_bono_enqueue_pedido()",
    "DROP FUNCTION IF EXISTS sell_in_bono_enqueue_bono()",
    "DROP FUNCTION IF EXISTS sell_in_bono_cubre(DATE, TEXT)",
]
