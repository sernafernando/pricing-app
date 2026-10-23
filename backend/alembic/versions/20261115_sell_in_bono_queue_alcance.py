"""bonus queue triggers: scope-aware gate (sell_in_bono_cubre_producto)

Revision ID: 20261115_sell_in_bono_queue_alcance
Revises: 20261114_merge_ads_permiso_sell_in_bonos
Create Date: 2026-10-22

sell-in-sell-out T3e-1 (M2b). Replaces the `sell_in_bono_dirty` triggers that
`20261107_sell_in_bonos_marca` installed with the ones of `app.services.sell_in.bono_queue`
for bonuses that reach a brand, a category, some models or one invoice
(`20261114_sell_in_bonos_alcance`) and may pay a percentage of the invoiced net:

- new gate `sell_in_bono_cubre_producto(fecha, pedido, item, marca, categoria)`;
  the product trigger consults it on the old and new side and also fires on a
  `categoria` change;
- new trigger on `sell_in_bono_items`: a models bonus's models queue the bonus;
- the bonus UPDATE trigger also watches the scope and kind columns (an invoice
  bonus whose operation is deleted gets `pedido_id` NULL and is queued);
- the invoiced-line UPDATE trigger also fires on `importe_neto` / `moneda`.

Both trigger sets are FROZEN copies here (`_PREVIOUS_*` is exactly what
20261107 installed, `_TRIGGERS_*` exactly today's `bono_queue` SQL, checked by
tests/unit/test_migration_sell_in_bonos_marca.py): the upgrade drops the
previous set and installs the new one, the downgrade the reverse. Postgres
only, like 20261107.

LOCK NOTE: re-creating the triggers takes SHARE ROW EXCLUSIVE on
`pedidos_compra`, `pedido_compra_lineas_facturadas`, `productos_erp`,
`sell_in_bonos_marca` and `sell_in_bono_items` for the transaction (writers
wait, readers do not). It runs with `lock_timeout = '5s'` and the deploy is
retried; the previous value is saved and restored because `env.py` runs every
pending revision in ONE transaction (same pattern as 20261114).
"""

from typing import List, Sequence, Union

from alembic import op

revision: str = "20261115_sell_in_bono_queue_alcance"
down_revision: Union[str, None] = "20261114_merge_ads_permiso_sell_in_bonos"
branch_labels: Union[str, Sequence[str], None] = None
depends_on: Union[str, Sequence[str], None] = None

LOCK_TIMEOUT = "5s"

# What 20261107_sell_in_bonos_marca installed (its trigger SQL minus `updated_at`), frozen.
_PREVIOUS_UP: List[str] = [
    """
CREATE OR REPLACE FUNCTION sell_in_bono_cubre(p_fecha DATE, p_marca TEXT DEFAULT NULL) RETURNS BOOLEAN AS $fn$
    SELECT p_fecha IS NOT NULL AND EXISTS (
        SELECT 1 FROM sell_in_bonos_marca AS b
        WHERE b.estado = 'activa' AND p_fecha BETWEEN b.fecha_desde AND b.fecha_hasta
          AND (p_marca IS NULL OR b.marca = p_marca)
    )
$fn$ LANGUAGE sql STABLE
""",
    """
CREATE OR REPLACE FUNCTION sell_in_bono_enqueue_bono() RETURNS TRIGGER AS $trg$
BEGIN
    IF NEW.estado = 'activa' OR (TG_OP = 'UPDATE' AND OLD.estado = 'activa') THEN
        INSERT INTO sell_in_bono_dirty (tipo, ref) VALUES ('bono', NEW.id) ON CONFLICT (tipo, ref) DO UPDATE SET enqueued_at = now(), attempts = 0, last_error = NULL;
        PERFORM pg_notify('sell_in_bono_dirty', '');
    END IF;
    RETURN NULL;
END;
$trg$ LANGUAGE plpgsql
""",
    """
CREATE OR REPLACE FUNCTION sell_in_bono_enqueue_pedido() RETURNS TRIGGER AS $trg$
DECLARE
    encolado BOOLEAN := false;
BEGIN
    IF TG_OP <> 'INSERT' AND sell_in_bono_cubre(OLD.fecha_factura) THEN
        INSERT INTO sell_in_bono_dirty (tipo, ref) VALUES ('pedido', OLD.id) ON CONFLICT (tipo, ref) DO UPDATE SET enqueued_at = now(), attempts = 0, last_error = NULL;
        encolado := true;
    END IF;
    IF TG_OP <> 'DELETE' AND sell_in_bono_cubre(NEW.fecha_factura) THEN
        INSERT INTO sell_in_bono_dirty (tipo, ref) VALUES ('pedido', NEW.id) ON CONFLICT (tipo, ref) DO UPDATE SET enqueued_at = now(), attempts = 0, last_error = NULL;
        encolado := true;
    END IF;
    IF encolado THEN
        PERFORM pg_notify('sell_in_bono_dirty', '');
    END IF;
    RETURN NULL;
END;
$trg$ LANGUAGE plpgsql
""",
    """
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
        PERFORM pg_notify('sell_in_bono_dirty', '');
    END IF;
    RETURN NULL;
END;
$trg$ LANGUAGE plpgsql
""",
    """
CREATE OR REPLACE FUNCTION sell_in_bono_enqueue_producto() RETURNS TRIGGER AS $trg$
DECLARE
    item productos_erp.item_id%TYPE;
BEGIN
    IF TG_OP = 'DELETE' THEN
        item := OLD.item_id;
    ELSE
        item := NEW.item_id;
    END IF;
    INSERT INTO sell_in_bono_dirty (tipo, ref)
    SELECT DISTINCT 'pedido', l.pedido_id
    FROM pedido_compra_lineas_facturadas AS l
    JOIN pedidos_compra AS p ON p.id = l.pedido_id
    WHERE l.item_id = item
      AND ((TG_OP <> 'DELETE' AND NEW.marca IS NOT NULL AND sell_in_bono_cubre(p.fecha_factura, NEW.marca))
           OR (TG_OP <> 'INSERT' AND OLD.marca IS NOT NULL AND sell_in_bono_cubre(p.fecha_factura, OLD.marca)))
    ORDER BY 2
    ON CONFLICT (tipo, ref) DO UPDATE SET enqueued_at = now(), attempts = 0, last_error = NULL;
    IF FOUND THEN
        PERFORM pg_notify('sell_in_bono_dirty', '');
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
    """
CREATE TRIGGER trg_sell_in_bono_productos_delete
AFTER DELETE ON productos_erp
FOR EACH ROW EXECUTE FUNCTION sell_in_bono_enqueue_producto()
""",
]

_PREVIOUS_DOWN: List[str] = [
    "DROP TRIGGER IF EXISTS trg_sell_in_bono_productos_delete ON productos_erp",
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

# `app.services.sell_in.bono_queue` UPGRADE_SQL / DOWNGRADE_SQL as of this revision, frozen.
_TRIGGERS_UP: List[str] = [
    """
CREATE OR REPLACE FUNCTION sell_in_bono_cubre(p_fecha DATE, p_marca TEXT DEFAULT NULL) RETURNS BOOLEAN AS $fn$
    SELECT p_fecha IS NOT NULL AND EXISTS (
        SELECT 1 FROM sell_in_bonos_marca AS b
        WHERE b.estado = 'activa' AND p_fecha BETWEEN b.fecha_desde AND b.fecha_hasta
          AND (p_marca IS NULL OR b.marca = p_marca)
    )
$fn$ LANGUAGE sql STABLE
""",
    """
CREATE OR REPLACE FUNCTION sell_in_bono_cubre_producto(
    p_fecha DATE, p_pedido BIGINT, p_item INTEGER, p_marca TEXT, p_categoria TEXT
) RETURNS BOOLEAN AS $fn$
    SELECT p_fecha IS NOT NULL AND EXISTS (
        SELECT 1 FROM sell_in_bonos_marca AS b
        WHERE b.estado = 'activa' AND p_fecha BETWEEN b.fecha_desde AND b.fecha_hasta
          AND (
            (b.alcance = 'marca' AND b.marca = p_marca)
            OR (b.alcance = 'categoria' AND b.categoria = p_categoria)
            OR (b.alcance = 'modelos'
                AND EXISTS (SELECT 1 FROM sell_in_bono_items AS i WHERE i.bono_id = b.id AND i.item_id = p_item))
            OR (b.alcance = 'factura' AND b.pedido_id = p_pedido)
          )
    )
$fn$ LANGUAGE sql STABLE
""",
    """
CREATE OR REPLACE FUNCTION sell_in_bono_enqueue_bono() RETURNS TRIGGER AS $trg$
BEGIN
    IF NEW.estado = 'activa' OR (TG_OP = 'UPDATE' AND OLD.estado = 'activa') THEN
        INSERT INTO sell_in_bono_dirty (tipo, ref) VALUES ('bono', NEW.id) ON CONFLICT (tipo, ref) DO UPDATE SET enqueued_at = now(), attempts = 0, last_error = NULL;
        PERFORM pg_notify('sell_in_bono_dirty', '');
    END IF;
    RETURN NULL;
END;
$trg$ LANGUAGE plpgsql
""",
    """
CREATE OR REPLACE FUNCTION sell_in_bono_enqueue_pedido() RETURNS TRIGGER AS $trg$
DECLARE
    encolado BOOLEAN := false;
BEGIN
    IF TG_OP <> 'INSERT' AND sell_in_bono_cubre(OLD.fecha_factura) THEN
        INSERT INTO sell_in_bono_dirty (tipo, ref) VALUES ('pedido', OLD.id) ON CONFLICT (tipo, ref) DO UPDATE SET enqueued_at = now(), attempts = 0, last_error = NULL;
        encolado := true;
    END IF;
    IF TG_OP <> 'DELETE' AND sell_in_bono_cubre(NEW.fecha_factura) THEN
        INSERT INTO sell_in_bono_dirty (tipo, ref) VALUES ('pedido', NEW.id) ON CONFLICT (tipo, ref) DO UPDATE SET enqueued_at = now(), attempts = 0, last_error = NULL;
        encolado := true;
    END IF;
    IF encolado THEN
        PERFORM pg_notify('sell_in_bono_dirty', '');
    END IF;
    RETURN NULL;
END;
$trg$ LANGUAGE plpgsql
""",
    """
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
        PERFORM pg_notify('sell_in_bono_dirty', '');
    END IF;
    RETURN NULL;
END;
$trg$ LANGUAGE plpgsql
""",
    """
CREATE OR REPLACE FUNCTION sell_in_bono_enqueue_bono_item() RETURNS TRIGGER AS $trg$
DECLARE
    bonos BIGINT[];
BEGIN
    IF TG_OP = 'INSERT' THEN
        bonos := ARRAY[NEW.bono_id];
    ELSIF TG_OP = 'DELETE' THEN
        bonos := ARRAY[OLD.bono_id];
    ELSE
        bonos := ARRAY[OLD.bono_id, NEW.bono_id];
    END IF;
    -- A bonus deleted with its models (CASCADE) is gone: nothing to queue.
    INSERT INTO sell_in_bono_dirty (tipo, ref)
    SELECT DISTINCT 'bono', b.id FROM sell_in_bonos_marca AS b
    WHERE b.id = ANY(bonos) AND b.estado = 'activa'
    ORDER BY 2
    ON CONFLICT (tipo, ref) DO UPDATE SET enqueued_at = now(), attempts = 0, last_error = NULL;
    IF FOUND THEN
        PERFORM pg_notify('sell_in_bono_dirty', '');
    END IF;
    RETURN NULL;
END;
$trg$ LANGUAGE plpgsql
""",
    """
CREATE OR REPLACE FUNCTION sell_in_bono_enqueue_producto() RETURNS TRIGGER AS $trg$
DECLARE
    item productos_erp.item_id%TYPE;
BEGIN
    IF TG_OP = 'DELETE' THEN
        item := OLD.item_id;
    ELSE
        item := NEW.item_id;
    END IF;
    INSERT INTO sell_in_bono_dirty (tipo, ref)
    SELECT DISTINCT 'pedido', l.pedido_id
    FROM pedido_compra_lineas_facturadas AS l
    JOIN pedidos_compra AS p ON p.id = l.pedido_id
    WHERE l.item_id = item
      AND ((TG_OP <> 'DELETE' AND sell_in_bono_cubre_producto(p.fecha_factura, p.id, item, NEW.marca, NEW.categoria))
           OR (TG_OP <> 'INSERT'
               AND sell_in_bono_cubre_producto(p.fecha_factura, p.id, item, OLD.marca, OLD.categoria)))
    ORDER BY 2
    ON CONFLICT (tipo, ref) DO UPDATE SET enqueued_at = now(), attempts = 0, last_error = NULL;
    IF FOUND THEN
        PERFORM pg_notify('sell_in_bono_dirty', '');
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
    (OLD.alcance, OLD.marca, OLD.categoria, OLD.pedido_id, OLD.tipo, OLD.monto_unit, OLD.porcentaje, OLD.moneda,
     OLD.fecha_desde, OLD.fecha_hasta, OLD.estado, OLD.usuario_id)
    IS DISTINCT FROM
    (NEW.alcance, NEW.marca, NEW.categoria, NEW.pedido_id, NEW.tipo, NEW.monto_unit, NEW.porcentaje, NEW.moneda,
     NEW.fecha_desde, NEW.fecha_hasta, NEW.estado, NEW.usuario_id)
)
EXECUTE FUNCTION sell_in_bono_enqueue_bono()
""",
    """
CREATE TRIGGER trg_sell_in_bono_items_change
AFTER INSERT OR UPDATE OR DELETE ON sell_in_bono_items
FOR EACH ROW EXECUTE FUNCTION sell_in_bono_enqueue_bono_item()
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
AFTER UPDATE OF pedido_id, item_id, cantidad, importe_neto, moneda ON pedido_compra_lineas_facturadas
FOR EACH ROW WHEN (
    (OLD.pedido_id, OLD.item_id, OLD.cantidad, OLD.importe_neto, OLD.moneda)
    IS DISTINCT FROM (NEW.pedido_id, NEW.item_id, NEW.cantidad, NEW.importe_neto, NEW.moneda)
)
EXECUTE FUNCTION sell_in_bono_enqueue_linea()
""",
    """
CREATE TRIGGER trg_sell_in_bono_productos_insert
AFTER INSERT ON productos_erp
FOR EACH ROW EXECUTE FUNCTION sell_in_bono_enqueue_producto()
""",
    """
CREATE TRIGGER trg_sell_in_bono_productos_marca
AFTER UPDATE OF marca, categoria ON productos_erp
FOR EACH ROW WHEN ((OLD.marca, OLD.categoria) IS DISTINCT FROM (NEW.marca, NEW.categoria))
EXECUTE FUNCTION sell_in_bono_enqueue_producto()
""",
    """
CREATE TRIGGER trg_sell_in_bono_productos_delete
AFTER DELETE ON productos_erp
FOR EACH ROW EXECUTE FUNCTION sell_in_bono_enqueue_producto()
""",
]

_TRIGGERS_DOWN: List[str] = [
    "DROP TRIGGER IF EXISTS trg_sell_in_bono_productos_delete ON productos_erp",
    "DROP TRIGGER IF EXISTS trg_sell_in_bono_productos_marca ON productos_erp",
    "DROP TRIGGER IF EXISTS trg_sell_in_bono_productos_insert ON productos_erp",
    "DROP TRIGGER IF EXISTS trg_sell_in_bono_lineas_update ON pedido_compra_lineas_facturadas",
    "DROP TRIGGER IF EXISTS trg_sell_in_bono_lineas_insert_delete ON pedido_compra_lineas_facturadas",
    "DROP TRIGGER IF EXISTS trg_sell_in_bono_pedidos_update ON pedidos_compra",
    "DROP TRIGGER IF EXISTS trg_sell_in_bono_pedidos_insert_delete ON pedidos_compra",
    "DROP TRIGGER IF EXISTS trg_sell_in_bono_items_change ON sell_in_bono_items",
    "DROP TRIGGER IF EXISTS trg_sell_in_bono_bonos_update ON sell_in_bonos_marca",
    "DROP TRIGGER IF EXISTS trg_sell_in_bono_bonos_insert ON sell_in_bonos_marca",
    "DROP FUNCTION IF EXISTS sell_in_bono_enqueue_producto()",
    "DROP FUNCTION IF EXISTS sell_in_bono_enqueue_bono_item()",
    "DROP FUNCTION IF EXISTS sell_in_bono_enqueue_linea()",
    "DROP FUNCTION IF EXISTS sell_in_bono_enqueue_pedido()",
    "DROP FUNCTION IF EXISTS sell_in_bono_enqueue_bono()",
    "DROP FUNCTION IF EXISTS sell_in_bono_cubre_producto(DATE, BIGINT, INTEGER, TEXT, TEXT)",
    "DROP FUNCTION IF EXISTS sell_in_bono_cubre(DATE, TEXT)",
]


def _is_postgres() -> bool:
    # plpgsql triggers and pg_notify: Postgres only (SQLite test schemas skip them).
    return op.get_bind().dialect.name == "postgresql"


def _run(statements: List[str]) -> None:
    if not _is_postgres():
        return
    # Restores the caller's lock_timeout (env.py runs every pending revision in one transaction).
    op.execute("SELECT set_config('bono_queue_alcance.lock_timeout_previo', current_setting('lock_timeout'), true)")
    op.execute(f"SELECT set_config('lock_timeout', '{LOCK_TIMEOUT}', true)")
    for statement in statements:
        op.execute(statement)
    op.execute("SELECT set_config('lock_timeout', current_setting('bono_queue_alcance.lock_timeout_previo'), true)")


def upgrade() -> None:
    _run(_PREVIOUS_DOWN + _TRIGGERS_UP)


def downgrade() -> None:
    _run(_TRIGGERS_DOWN + _PREVIOUS_UP)
