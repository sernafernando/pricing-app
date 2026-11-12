"""The sell-in queue gates an operation on its own invoice bonus, whatever that bonus's range

Revision ID: 20261112_sell_in_bono_cubre_pedido
Revises: 20261112_producto_envio_eleccion
Create Date: 2026-11-12

Sell in factura pendiente (owner): "la carga con factura de sell in tiene que poder cargarse y aplicar recién cuando
se agregue una factura no al revés". An invoice line may be saved before Compras links its operation's supplier
invoice; its bonus then holds a placeholder day (the save date) until the reconcile moves it to the invoice's date
(`bonos._seguir_factura`). The `pedidos_compra` and invoiced-line triggers gated an operation only on an active
bonus's range covering its invoice date, so linking an invoice dated outside that placeholder day queued nothing.

New `sell_in_bono_cubre_pedido(fecha, pedido)`: the old date gate (`sell_in_bono_cubre`, unchanged) OR an active
invoice bonus of that very operation once it has an invoice date. `sell_in_bono_enqueue_pedido` and
`sell_in_bono_enqueue_linea` call it instead of the date gate; every other case queues exactly as before. The
triggers call the functions by name, so CREATE OR REPLACE is enough: no trigger is dropped and no row is touched.

The module copy (`app.services.sell_in.bono_queue.UPGRADE_SQL`) must equal the frozen copies below. The downgrade
puts back 20261115's two functions, then drops the new gate.
"""

from typing import List, Sequence, Union

from alembic import op

revision: str = "20261112_sell_in_bono_cubre_pedido"
down_revision: Union[str, None] = "20261112_producto_envio_eleccion"
branch_labels: Union[str, Sequence[str], None] = None
depends_on: Union[str, Sequence[str], None] = None

# Frozen copies. *_UP: what this revision installs (the module's statements); *_DOWN: what it replaced
# (20261115_sell_in_bono_queue_alcance's operation and line functions).
FUNCIONES_UP: List[str] = [
    """
CREATE OR REPLACE FUNCTION sell_in_bono_cubre_pedido(p_fecha DATE, p_pedido BIGINT) RETURNS BOOLEAN AS $fn$
    SELECT sell_in_bono_cubre(p_fecha) OR (p_fecha IS NOT NULL AND EXISTS (
        SELECT 1 FROM sell_in_bonos_marca AS b
        WHERE b.estado = 'activa' AND b.alcance = 'factura' AND b.pedido_id = p_pedido
    ))
$fn$ LANGUAGE sql STABLE
""",
    """
CREATE OR REPLACE FUNCTION sell_in_bono_enqueue_pedido() RETURNS TRIGGER AS $trg$
DECLARE
    encolado BOOLEAN := false;
BEGIN
    IF TG_OP <> 'INSERT' AND sell_in_bono_cubre_pedido(OLD.fecha_factura, OLD.id) THEN
        INSERT INTO sell_in_bono_dirty (tipo, ref) VALUES ('pedido', OLD.id) ON CONFLICT (tipo, ref) DO UPDATE SET enqueued_at = now(), attempts = 0, last_error = NULL;
        encolado := true;
    END IF;
    IF TG_OP <> 'DELETE' AND sell_in_bono_cubre_pedido(NEW.fecha_factura, NEW.id) THEN
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
    WHERE p.id = ANY(pedidos) AND sell_in_bono_cubre_pedido(p.fecha_factura, p.id)
    ORDER BY 2
    ON CONFLICT (tipo, ref) DO UPDATE SET enqueued_at = now(), attempts = 0, last_error = NULL;
    IF FOUND THEN
        PERFORM pg_notify('sell_in_bono_dirty', '');
    END IF;
    RETURN NULL;
END;
$trg$ LANGUAGE plpgsql
""",
]

FUNCIONES_DOWN: List[str] = [
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
]


def upgrade() -> None:
    op.execute("SELECT set_config('lock_timeout', '5s', false)")
    for statement in FUNCIONES_UP:
        op.execute(statement)


def downgrade() -> None:
    op.execute("SELECT set_config('lock_timeout', '5s', false)")
    for statement in FUNCIONES_DOWN:
        op.execute(statement)
    op.execute("DROP FUNCTION IF EXISTS sell_in_bono_cubre_pedido(DATE, BIGINT)")
