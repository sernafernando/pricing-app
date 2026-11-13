"""The sell-in queue gates an operation on its applied invoice totals too (sell in varias facturas S2)

Revision ID: 20261114_sell_in_cubre_totales_aplicados
Revises: 20261114_marcas_visibles_excepciones
Create Date: 2026-11-13

Owner 2026-11-13: "por defecto tendría que aplicar a todas las facturas el sell in". A tactical's invoice total is one
sell-in purchase split over its operation's invoiced lines; when another invoice of that operation links later, the
`sell_in.bono` worker re-splits it over all of them (`app.services.tacticals.repartir_totales_de_factura`). The gate
`sell_in_bono_cubre_pedido` only let in an operation with an active invoice bonus or a WAITING total, so a second
invoice of an operation whose total was already applied queued nothing. It now also lets in an operation linked to an
active tactical purchase (`sell_in_compras.tactical_id`, via `sell_in_compra_pedidos`, indexed on the operation).
CREATE OR REPLACE only: no table, trigger or row is touched.

The module copy (`app.services.sell_in.bono_queue.UPGRADE_SQL`) must equal the frozen copy below. The downgrade puts
back 20261112_tactical_facturas_pendientes's gate.
"""

from typing import List, Sequence, Union

from alembic import op

revision: str = "20261114_sell_in_cubre_totales_aplicados"
down_revision: Union[str, None] = "20261114_marcas_visibles_excepciones"
branch_labels: Union[str, Sequence[str], None] = None
depends_on: Union[str, Sequence[str], None] = None

# Frozen copies. *_UP: what this revision installs (the module's statement); *_DOWN: what it replaced.
FUNCIONES_UP: List[str] = [
    """
CREATE OR REPLACE FUNCTION sell_in_bono_cubre_pedido(p_fecha DATE, p_pedido BIGINT) RETURNS BOOLEAN AS $fn$
    SELECT sell_in_bono_cubre(p_fecha) OR (p_fecha IS NOT NULL AND (
        EXISTS (
            SELECT 1 FROM sell_in_bonos_marca AS b
            WHERE b.estado = 'activa' AND b.alcance = 'factura' AND b.pedido_id = p_pedido
        )
        OR EXISTS (
            SELECT 1 FROM tactical_facturas_pendientes AS t
            WHERE t.estado = 'pendiente' AND t.pedido_id = p_pedido
        )
        OR EXISTS (
            SELECT 1 FROM sell_in_compra_pedidos AS cp
            JOIN sell_in_compras AS c ON c.id = cp.compra_id
            WHERE cp.pedido_compra_id = p_pedido AND c.estado = 'activa' AND c.tactical_id IS NOT NULL
        )
    ))
$fn$ LANGUAGE sql STABLE
""",
]

FUNCIONES_DOWN: List[str] = [
    """
CREATE OR REPLACE FUNCTION sell_in_bono_cubre_pedido(p_fecha DATE, p_pedido BIGINT) RETURNS BOOLEAN AS $fn$
    SELECT sell_in_bono_cubre(p_fecha) OR (p_fecha IS NOT NULL AND (
        EXISTS (
            SELECT 1 FROM sell_in_bonos_marca AS b
            WHERE b.estado = 'activa' AND b.alcance = 'factura' AND b.pedido_id = p_pedido
        )
        OR EXISTS (
            SELECT 1 FROM tactical_facturas_pendientes AS t
            WHERE t.estado = 'pendiente' AND t.pedido_id = p_pedido
        )
    ))
$fn$ LANGUAGE sql STABLE
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
