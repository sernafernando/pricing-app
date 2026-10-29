"""The % of the sale's cost bonuses follow a sale's cost and a product's brand, category or VAT rate

Revision ID: 20261213_sell_in_bono_costo_triggers
Revises: 20261212_sell_in_bono_costo
Create Date: 2026-10-29

sell-in-sell-out T25b2 (S30). A % of the sale's cost bonus (`base = 'costo_venta'`, `services/sell_in/bonos_costo.py`)
discounts a % of the cost recorded on each sale of its scope; two changes it reads did not queue it:

- `ventas_fuera_ml_metricas` / `ventas_tienda_nube_metricas`: the `sell_dirty` UPDATE triggers also watch
  `costo_total` (the bonus's base is `costo_total / units`, `sell_out.alcance.ventas`), so a cost change queues the
  line for `sell.drain`. The rest of their definition is 20261031's, unchanged. (ML's `mcosto` already queues through
  `sale_lines_store.SELL_COLUMNS`.)
- `productos_erp`: `sell_in_bono_enqueue_producto` also queues `('bono', id)` for every active cost bonus reaching the
  product on its old or new side (brand, category or listed model), and its update trigger also fires on `iva`; an
  `iva` change alone queues only the cost bonuses with `incluye_iva` and no invoice operation (an invoice bonus never
  reads it). What it queued before (the invoice operations, 20261115) is unchanged.

The module copies (`app.services.sell.queue.UPGRADE_SQL`, `app.services.sell_in.bono_queue.UPGRADE_SQL`) must equal
the frozen copies below. The downgrade puts back 20261031's two triggers and 20261115's function and trigger.

LOCK NOTE: DROP/CREATE TRIGGER takes a SHARE ROW EXCLUSIVE lock on `ventas_fuera_ml_metricas`,
`ventas_tienda_nube_metricas` and `productos_erp`, which the ERP sync writes. Upgrade and downgrade run with
`lock_timeout = '5s'` and the deploy is retried; the previous value is saved and restored because `env.py` runs every
pending revision in ONE transaction (same pattern as 20261211/20261212). Every step is idempotent.
"""

from typing import List, Sequence, Union

from alembic import op

revision: str = "20261213_sell_in_bono_costo_triggers"
down_revision: Union[str, None] = "20261212_sell_in_bono_costo"
branch_labels: Union[str, Sequence[str], None] = None
depends_on: Union[str, Sequence[str], None] = None

LOCK_TIMEOUT = "5s"

# Frozen copies. *_UP: what this revision installs (the module's statements); *_DOWN: what it replaced.
PRODUCTO_UP = [
    """
CREATE OR REPLACE FUNCTION sell_in_bono_enqueue_producto() RETURNS TRIGGER AS $trg$
DECLARE
    item productos_erp.item_id%TYPE;
    solo_iva BOOLEAN := false;
    encolado BOOLEAN := false;
BEGIN
    IF TG_OP = 'DELETE' THEN
        item := OLD.item_id;
    ELSE
        item := NEW.item_id;
    END IF;
    IF TG_OP = 'UPDATE' THEN
        solo_iva := (OLD.marca, OLD.categoria) IS NOT DISTINCT FROM (NEW.marca, NEW.categoria);
    END IF;
    IF NOT solo_iva THEN
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
        encolado := FOUND;
    END IF;
    -- % of the sale's cost bonuses (T25b2): no invoice date to gate on; an `iva` change alone moves only the ones
    -- loaded with VAT. Same scope rule as `sell_in_bono_cubre_producto` (a cost bonus is never by invoice).
    INSERT INTO sell_in_bono_dirty (tipo, ref)
    SELECT DISTINCT 'bono', b.id FROM sell_in_bonos_marca AS b
    WHERE b.estado = 'activa' AND b.base = 'costo_venta' AND (NOT solo_iva OR b.incluye_iva)
      AND ((b.alcance = 'modelos'
            AND EXISTS (SELECT 1 FROM sell_in_bono_items AS i WHERE i.bono_id = b.id AND i.item_id = item))
           OR (TG_OP <> 'DELETE'
               AND ((b.alcance = 'marca' AND b.marca = NEW.marca) OR (b.alcance = 'categoria' AND b.categoria = NEW.categoria)))
           OR (TG_OP <> 'INSERT'
               AND ((b.alcance = 'marca' AND b.marca = OLD.marca) OR (b.alcance = 'categoria' AND b.categoria = OLD.categoria))))
    ORDER BY 2
    ON CONFLICT (tipo, ref) DO UPDATE SET enqueued_at = now(), attempts = 0, last_error = NULL;
    IF encolado OR FOUND THEN
        PERFORM pg_notify('sell_in_bono_dirty', '');
    END IF;
    RETURN NULL;
END;
$trg$ LANGUAGE plpgsql
""",
    """
CREATE TRIGGER trg_sell_in_bono_productos_marca
AFTER UPDATE OF marca, categoria, iva ON productos_erp
FOR EACH ROW WHEN ((OLD.marca, OLD.categoria, OLD.iva) IS DISTINCT FROM (NEW.marca, NEW.categoria, NEW.iva))
EXECUTE FUNCTION sell_in_bono_enqueue_producto()
""",
]

PRODUCTO_DOWN = [
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
CREATE TRIGGER trg_sell_in_bono_productos_marca
AFTER UPDATE OF marca, categoria ON productos_erp
FOR EACH ROW WHEN ((OLD.marca, OLD.categoria) IS DISTINCT FROM (NEW.marca, NEW.categoria))
EXECUTE FUNCTION sell_in_bono_enqueue_producto()
""",
]

SELL_DIRTY_UP = [
    """
CREATE TRIGGER trg_sell_dirty_fuera_update
AFTER UPDATE OF it_transaction, item_id, cantidad, fecha_venta, signo, monto_total, costo_unitario, costo_total
ON ventas_fuera_ml_metricas
FOR EACH ROW WHEN (
    (OLD.it_transaction, OLD.item_id, OLD.cantidad, OLD.fecha_venta, OLD.signo, OLD.monto_total, OLD.costo_unitario,
     OLD.costo_total)
    IS DISTINCT FROM
    (NEW.it_transaction, NEW.item_id, NEW.cantidad, NEW.fecha_venta, NEW.signo, NEW.monto_total, NEW.costo_unitario,
     NEW.costo_total)
)
EXECUTE FUNCTION sell_dirty_enqueue_venta('fuera')
""",
    """
CREATE TRIGGER trg_sell_dirty_tn_update
AFTER UPDATE OF it_transaction, item_id, cantidad, fecha_venta, signo, monto_total, costo_unitario, costo_total
ON ventas_tienda_nube_metricas
FOR EACH ROW WHEN (
    (OLD.it_transaction, OLD.item_id, OLD.cantidad, OLD.fecha_venta, OLD.signo, OLD.monto_total, OLD.costo_unitario,
     OLD.costo_total)
    IS DISTINCT FROM
    (NEW.it_transaction, NEW.item_id, NEW.cantidad, NEW.fecha_venta, NEW.signo, NEW.monto_total, NEW.costo_unitario,
     NEW.costo_total)
)
EXECUTE FUNCTION sell_dirty_enqueue_venta('tn')
""",
]

SELL_DIRTY_DOWN = [
    """
CREATE TRIGGER trg_sell_dirty_fuera_update
AFTER UPDATE OF it_transaction, item_id, cantidad, fecha_venta, signo, monto_total, costo_unitario
ON ventas_fuera_ml_metricas
FOR EACH ROW WHEN (
    (OLD.it_transaction, OLD.item_id, OLD.cantidad, OLD.fecha_venta, OLD.signo, OLD.monto_total, OLD.costo_unitario)
    IS DISTINCT FROM
    (NEW.it_transaction, NEW.item_id, NEW.cantidad, NEW.fecha_venta, NEW.signo, NEW.monto_total, NEW.costo_unitario)
)
EXECUTE FUNCTION sell_dirty_enqueue_venta('fuera')
""",
    """
CREATE TRIGGER trg_sell_dirty_tn_update
AFTER UPDATE OF it_transaction, item_id, cantidad, fecha_venta, signo, monto_total, costo_unitario
ON ventas_tienda_nube_metricas
FOR EACH ROW WHEN (
    (OLD.it_transaction, OLD.item_id, OLD.cantidad, OLD.fecha_venta, OLD.signo, OLD.monto_total, OLD.costo_unitario)
    IS DISTINCT FROM
    (NEW.it_transaction, NEW.item_id, NEW.cantidad, NEW.fecha_venta, NEW.signo, NEW.monto_total, NEW.costo_unitario)
)
EXECUTE FUNCTION sell_dirty_enqueue_venta('tn')
""",
]

DROPS = [
    "DROP TRIGGER IF EXISTS trg_sell_in_bono_productos_marca ON productos_erp",
    "DROP TRIGGER IF EXISTS trg_sell_dirty_fuera_update ON ventas_fuera_ml_metricas",
    "DROP TRIGGER IF EXISTS trg_sell_dirty_tn_update ON ventas_tienda_nube_metricas",
]


def _run(statements: List[str]) -> None:
    # Plain SQL (works in offline `--sql` mode); restores the caller's lock_timeout.
    op.execute("SELECT set_config('bono_costo_triggers.lock_timeout_previo', current_setting('lock_timeout'), true)")
    op.execute(f"SELECT set_config('lock_timeout', '{LOCK_TIMEOUT}', true)")
    for statement in statements:
        op.execute(statement)
    op.execute("SELECT set_config('lock_timeout', current_setting('bono_costo_triggers.lock_timeout_previo'), true)")


def upgrade() -> None:
    _run([*DROPS, *PRODUCTO_UP, *SELL_DIRTY_UP])


def downgrade() -> None:
    _run([*DROPS, *PRODUCTO_DOWN, *SELL_DIRTY_DOWN])
