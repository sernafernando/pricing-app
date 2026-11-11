"""sell_in_bonos_marca: a brand bonus may carry a category

Revision ID: 20261111_sell_in_bono_marca_categoria
Revises: 20261110_pedido_compra_facturas
Create Date: 2026-11-11

SISO S3 (owner): "Que se puedan combinar marca y categoría porque hoy no se puede, si quiero aplicar a los routers
solo de tp-link no puedo." A bonus with `alcance = 'marca'` may set `categoria`: it then reaches only that brand's
products of that category. The CHECK changes, and the sell-in queue's two product functions
(`sell_in_bono_cubre_producto`, `sell_in_bono_enqueue_producto`) read the category too, so a product change queues a
brand line with a category only when the product is, or was, in it. No row is touched.

Downgrade restores the old functions and the old CHECK, which fails while a brand bonus carries a category (it never drops data).
"""

from typing import List, Sequence, Union

from alembic import op

revision: str = "20261111_sell_in_bono_marca_categoria"
down_revision: Union[str, None] = "20261110_pedido_compra_facturas"
branch_labels: Union[str, Sequence[str], None] = None
depends_on: Union[str, Sequence[str], None] = None

NOMBRE = "ck_sell_in_bonos_marca_campos_segun_alcance"
RESTO = (
    "OR (alcance = 'categoria' AND categoria IS NOT NULL AND marca IS NULL AND pedido_id IS NULL) "
    "OR (alcance = 'modelos' AND marca IS NULL AND categoria IS NULL AND pedido_id IS NULL) "
    "OR (alcance = 'factura' AND marca IS NULL AND categoria IS NULL)"
)
NUEVO = f"(alcance = 'marca' AND marca IS NOT NULL AND pedido_id IS NULL) {RESTO}"
VIEJO = f"(alcance = 'marca' AND marca IS NOT NULL AND categoria IS NULL AND pedido_id IS NULL) {RESTO}"

# Frozen copies of `app.services.sell_in.bono_queue.UPGRADE_SQL`'s two product functions. *_UP: what this revision
# installs (a brand line with a category reaches only that category); *_DOWN: what it replaced (20261115's
# `sell_in_bono_cubre_producto`, 20261213's `sell_in_bono_enqueue_producto`). The triggers call them by name, so
# CREATE OR REPLACE is enough: no trigger is dropped.
FUNCIONES_UP: List[str] = [
    """
CREATE OR REPLACE FUNCTION sell_in_bono_cubre_producto(
    p_fecha DATE, p_pedido BIGINT, p_item INTEGER, p_marca TEXT, p_categoria TEXT
) RETURNS BOOLEAN AS $fn$
    SELECT p_fecha IS NOT NULL AND EXISTS (
        SELECT 1 FROM sell_in_bonos_marca AS b
        WHERE b.estado = 'activa' AND p_fecha BETWEEN b.fecha_desde AND b.fecha_hasta
          AND (
            (b.alcance = 'marca' AND b.marca = p_marca AND (b.categoria IS NULL OR b.categoria = p_categoria))
            OR (b.alcance = 'categoria' AND b.categoria = p_categoria)
            OR (b.alcance = 'modelos'
                AND EXISTS (SELECT 1 FROM sell_in_bono_items AS i WHERE i.bono_id = b.id AND i.item_id = p_item))
            OR (b.alcance = 'factura' AND b.pedido_id = p_pedido)
          )
    )
$fn$ LANGUAGE sql STABLE
""",
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
               AND ((b.alcance = 'marca' AND b.marca = NEW.marca
                     AND (b.categoria IS NULL OR b.categoria = NEW.categoria))
                    OR (b.alcance = 'categoria' AND b.categoria = NEW.categoria)))
           OR (TG_OP <> 'INSERT'
               AND ((b.alcance = 'marca' AND b.marca = OLD.marca
                     AND (b.categoria IS NULL OR b.categoria = OLD.categoria))
                    OR (b.alcance = 'categoria' AND b.categoria = OLD.categoria))))
    ORDER BY 2
    ON CONFLICT (tipo, ref) DO UPDATE SET enqueued_at = now(), attempts = 0, last_error = NULL;
    IF encolado OR FOUND THEN
        PERFORM pg_notify('sell_in_bono_dirty', '');
    END IF;
    RETURN NULL;
END;
$trg$ LANGUAGE plpgsql
""",
]
FUNCIONES_DOWN: List[str] = [
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
]


def upgrade() -> None:
    op.execute("SELECT set_config('lock_timeout', '5s', false)")
    op.drop_constraint(NOMBRE, "sell_in_bonos_marca", type_="check")
    op.create_check_constraint(NOMBRE, "sell_in_bonos_marca", NUEVO)
    for statement in FUNCIONES_UP:
        op.execute(statement)


def downgrade() -> None:
    op.execute("SELECT set_config('lock_timeout', '5s', false)")
    op.drop_constraint(NOMBRE, "sell_in_bonos_marca", type_="check")
    op.create_check_constraint(NOMBRE, "sell_in_bonos_marca", VIEJO)
    for statement in FUNCIONES_DOWN:
        op.execute(statement)
