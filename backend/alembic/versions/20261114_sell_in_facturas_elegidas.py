"""Sell in varias facturas S3-S5: invoiced lines per invoice, and a tactical invoice line's pick of invoices

Revision ID: 20261114_sell_in_facturas_elegidas
Revises: 20261114_sell_in_cubre_totales_aplicados
Create Date: 2026-11-13

Owner 2026-11-13: "por defecto tendría que aplicar a todas las facturas el sell in, pero hay que hacer que se pueda
modificar eso y elegir las facturas en caso que tenga que aplicarse a una sola, dentro del propio editor". Additive:

- `pedido_compra_lineas_facturadas_ct` (`app.models.pedido_compra_linea_facturada_ct`): the per-invoice split of
  `pedido_compra_lineas_facturadas`, one bucket per linked invoice plus a signed one (`ct_transaction_id` NULL) for
  the credit notes imputed to the whole operation. Backfilled here from the ERP mirror with a frozen copy of
  `erp_matching_service._LINEAS_CT_ORIGEN_SQL` (every operation), before its queue triggers exist, so the backfill
  queues nothing; from then on `reconciliar_lineas_facturadas` keeps it in step with the aggregate.
- Its queue triggers (`bono_queue.LINEAS_CT_SQL`, frozen below), on the existing `sell_in_bono_enqueue_linea`.
- `tactical_linea_facturas` (`app.models.tactical.TacticalLineaFactura`): the invoices a tactical invoice line picks;
  no row = every invoice (the default, and every existing line).

No existing table, row or function changes. The downgrade drops what it created (a pick is lost with it: the lines
go back to every invoice).
"""

from typing import List, Sequence, Union

import sqlalchemy as sa
from alembic import op

revision: str = "20261114_sell_in_facturas_elegidas"
down_revision: Union[str, None] = "20261114_sell_in_cubre_totales_aplicados"
branch_labels: Union[str, Sequence[str], None] = None
depends_on: Union[str, Sequence[str], None] = None

LINEAS_CT = "pedido_compra_lineas_facturadas_ct"
ELEGIDAS = "tactical_linea_facturas"

# Frozen copy of `app.services.sell_in.bono_queue.LINEAS_CT_SQL`.
TRIGGERS_UP: List[str] = [
    """
CREATE TRIGGER trg_sell_in_bono_lineas_ct_insert_delete
AFTER INSERT OR DELETE ON pedido_compra_lineas_facturadas_ct
FOR EACH ROW EXECUTE FUNCTION sell_in_bono_enqueue_linea()
""",
    """
CREATE TRIGGER trg_sell_in_bono_lineas_ct_update
AFTER UPDATE OF pedido_id, ct_transaction_id, item_id, cantidad, importe_neto, moneda
ON pedido_compra_lineas_facturadas_ct
FOR EACH ROW WHEN (
    (OLD.pedido_id, OLD.ct_transaction_id, OLD.item_id, OLD.cantidad, OLD.importe_neto, OLD.moneda)
    IS DISTINCT FROM (NEW.pedido_id, NEW.ct_transaction_id, NEW.item_id, NEW.cantidad, NEW.importe_neto, NEW.moneda)
)
EXECUTE FUNCTION sell_in_bono_enqueue_linea()
""",
]
TRIGGERS_DOWN: List[str] = [
    f"DROP TRIGGER IF EXISTS trg_sell_in_bono_lineas_ct_update ON {LINEAS_CT}",
    f"DROP TRIGGER IF EXISTS trg_sell_in_bono_lineas_ct_insert_delete ON {LINEAS_CT}",
]

# Frozen copy of `erp_matching_service._LINEAS_CT_ORIGEN_SQL` over every operation (`scope_pedido` = 1 = 1).
# FROZEN: it is what this revision backfilled, not the runtime SQL. Do not edit it when `_LINEAS_CT_ORIGEN_SQL`
# changes later; `test_the_migration_backfill_matches_the_reconcile` (tests/services/test_lineas_facturadas_postgres.py)
# guards that, today, both give the same rows.
ORIGEN_SQL = """
SELECT d.pedido_id AS pedido_id, d.factura AS factura, it.item_id AS item_id, CAST(FLOOR(SUM(it.it_qty * v.sd_plusorminus)) AS INTEGER) AS cantidad, CASE WHEN COUNT(DISTINCT it.curr_id) = 1 AND COUNT(it.curr_id) = COUNT(*) AND COUNT(it.it_price) = COUNT(*) AND MIN(it.curr_id) IN (1, 2) THEN CASE WHEN d.factura IS NOT NULL AND SUM(it.it_qty * it.it_price * v.sd_plusorminus) < 0 THEN 0 ELSE ROUND(SUM(it.it_qty * it.it_price * v.sd_plusorminus), 2) END END AS importe_neto, CASE WHEN COUNT(DISTINCT it.curr_id) = 1 AND COUNT(it.curr_id) = COUNT(*) AND COUNT(it.it_price) = COUNT(*) AND MIN(it.curr_id) IN (1, 2) THEN CASE MIN(it.curr_id) WHEN 1 THEN 'ARS' ELSE 'USD' END END AS moneda FROM (SELECT docs.pedido_id AS pedido_id, docs.ct AS ct, MAX(docs.factura) AS factura FROM (SELECT links.pedido_id AS pedido_id, links.ct AS ct, links.ct AS factura FROM (
SELECT f.pedido_id AS pedido_id, f.ct_transaction_id AS ct
FROM pedido_compra_facturas f
JOIN pedidos_compra p ON p.id = f.pedido_id
WHERE 1 = 1
UNION
SELECT p.id AS pedido_id, p.ct_transaction_id AS ct
FROM pedidos_compra p
WHERE p.ct_transaction_id IS NOT NULL AND 1 = 1
  AND NOT EXISTS (
    SELECT 1 FROM pedido_compra_facturas f2 WHERE f2.pedido_id = p.id
  )
) links WHERE (
  SELECT COUNT(*) FROM (
    SELECT f.pedido_id AS pid FROM pedido_compra_facturas f
    WHERE f.ct_transaction_id = links.ct
    UNION
    SELECT px.id FROM pedidos_compra px
    WHERE px.ct_transaction_id = links.ct
  ) owners
) = 1
UNION
SELECT links.pedido_id, n.ct, CASE WHEN n.destino_tipo = 'factura_erp' THEN links.ct END
FROM (
SELECT f.pedido_id AS pedido_id, f.ct_transaction_id AS ct
FROM pedido_compra_facturas f
JOIN pedidos_compra p ON p.id = f.pedido_id
WHERE 1 = 1
UNION
SELECT p.id AS pedido_id, p.ct_transaction_id AS ct
FROM pedidos_compra p
WHERE p.ct_transaction_id IS NOT NULL AND 1 = 1
  AND NOT EXISTS (
    SELECT 1 FROM pedido_compra_facturas f2 WHERE f2.pedido_id = p.id
  )
) links
JOIN (
  WITH RECURSIVE cadena(pedido_id, ancestro_id) AS (
    SELECT links.pedido_id, links.pedido_id FROM (
SELECT f.pedido_id AS pedido_id, f.ct_transaction_id AS ct
FROM pedido_compra_facturas f
JOIN pedidos_compra p ON p.id = f.pedido_id
WHERE 1 = 1
UNION
SELECT p.id AS pedido_id, p.ct_transaction_id AS ct
FROM pedidos_compra p
WHERE p.ct_transaction_id IS NOT NULL AND 1 = 1
  AND NOT EXISTS (
    SELECT 1 FROM pedido_compra_facturas f2 WHERE f2.pedido_id = p.id
  )
) links WHERE (
  SELECT COUNT(*) FROM (
    SELECT f.pedido_id AS pid FROM pedido_compra_facturas f
    WHERE f.ct_transaction_id = links.ct
    UNION
    SELECT px.id FROM pedidos_compra px
    WHERE px.ct_transaction_id = links.ct
  ) owners
) = 1
    UNION
    SELECT c.pedido_id, a.corregido_desde_id
    FROM cadena c JOIN pedidos_compra a ON a.id = c.ancestro_id
    WHERE a.corregido_desde_id IS NOT NULL
  )
  SELECT pedido_id, ancestro_id FROM cadena
) cad ON cad.pedido_id = links.pedido_id
JOIN (
  SELECT i.destino_tipo, i.destino_id,
         CASE WHEN i.origen_tipo = 'nota_credito_erp' THEN i.origen_id ELSE ncl.ct_transaction_id END AS ct
  FROM imputaciones i
  LEFT JOIN notas_credito_local ncl ON i.origen_tipo = 'nota_credito_local' AND ncl.id = i.origen_id
  WHERE i.origen_tipo IN ('nota_credito_erp', 'nota_credito_local')
    AND i.es_reversal = false
    AND NOT EXISTS (SELECT 1 FROM imputaciones r WHERE r.es_reversal = true AND r.reimputada_desde_id = i.id)
) n ON (n.destino_tipo = 'pedido_compra' AND n.destino_id = cad.ancestro_id)
    OR (n.destino_tipo = 'factura_erp' AND n.destino_id = links.ct)
JOIN v_facturas_compra_vigentes vn ON vn.ct_transaction = n.ct AND vn.clasificacion = 'NC'
WHERE (
  SELECT COUNT(*) FROM (
    SELECT f.pedido_id AS pid FROM pedido_compra_facturas f
    WHERE f.ct_transaction_id = links.ct
    UNION
    SELECT px.id FROM pedidos_compra px
    WHERE px.ct_transaction_id = links.ct
  ) owners
) = 1) docs GROUP BY docs.pedido_id, docs.ct) d JOIN v_facturas_compra_vigentes v ON v.ct_transaction = d.ct
JOIN tb_item_transactions it ON it.ct_transaction = d.ct
WHERE it.item_id IS NOT NULL
  AND NOT (
    COALESCE(it.it_isassociation, false) = true
    AND COALESCE(it.it_order, 1) <> 1
    AND it.it_isassociationgroup IS NOT NULL
  )
GROUP BY d.pedido_id, d.factura, it.item_id
HAVING (d.factura IS NOT NULL AND SUM(it.it_qty * v.sd_plusorminus) >= 1)
    OR (d.factura IS NULL AND CAST(FLOOR(SUM(it.it_qty * v.sd_plusorminus)) AS INTEGER) <> 0)
"""
BACKFILL_SQL = (
    f"INSERT INTO {LINEAS_CT} (pedido_id, ct_transaction_id, item_id, cantidad, importe_neto, moneda) "
    "SELECT s.pedido_id, s.factura, s.item_id, s.cantidad, s.importe_neto, s.moneda FROM (" + ORIGEN_SQL + ") s"
)


def _lock_timeout() -> None:
    # env.py runs every pending revision in ONE transaction: save the caller's lock_timeout and set ours for this
    # transaction (plain SQL, works in offline `--sql` mode); `_restaurar_lock_timeout` puts it back.
    op.execute("SELECT set_config('facturas_elegidas.lock_timeout_previo', current_setting('lock_timeout'), true)")
    op.execute("SELECT set_config('lock_timeout', '5s', true)")


def _restaurar_lock_timeout() -> None:
    op.execute("SELECT set_config('lock_timeout', current_setting('facturas_elegidas.lock_timeout_previo'), true)")


def upgrade() -> None:
    _lock_timeout()
    op.create_table(
        LINEAS_CT,
        sa.Column("id", sa.BigInteger(), primary_key=True),
        sa.Column("pedido_id", sa.BigInteger(), sa.ForeignKey("pedidos_compra.id", ondelete="CASCADE"), nullable=False),
        sa.Column("ct_transaction_id", sa.BigInteger(), nullable=True),
        sa.Column("item_id", sa.Integer(), nullable=False),
        sa.Column("cantidad", sa.Integer(), nullable=False),
        sa.Column("importe_neto", sa.Numeric(18, 2), nullable=True),
        sa.Column("moneda", sa.String(3), nullable=True),
        sa.CheckConstraint("cantidad <> 0", name="ck_pedido_compra_lineas_facturadas_ct_cantidad"),
        sa.CheckConstraint("moneda IN ('ARS', 'USD')", name="ck_pedido_compra_lineas_facturadas_ct_moneda"),
    )
    op.create_index("ix_pedido_compra_lineas_facturadas_ct_pedido_id", LINEAS_CT, ["pedido_id"])
    op.create_index(
        "uq_pedido_compra_lineas_facturadas_ct_factura",
        LINEAS_CT,
        ["pedido_id", "ct_transaction_id", "item_id"],
        unique=True,
        postgresql_where=sa.text("ct_transaction_id IS NOT NULL"),
    )
    op.create_index(
        "uq_pedido_compra_lineas_facturadas_ct_pedido",
        LINEAS_CT,
        ["pedido_id", "item_id"],
        unique=True,
        postgresql_where=sa.text("ct_transaction_id IS NULL"),
    )
    op.create_table(
        ELEGIDAS,
        sa.Column("id", sa.BigInteger(), primary_key=True),
        sa.Column("tactical_id", sa.BigInteger(), sa.ForeignKey("tacticals.id", ondelete="CASCADE"), nullable=False),
        sa.Column("tactical_linea", sa.Integer(), nullable=False),
        sa.Column("ct_transaction_id", sa.BigInteger(), nullable=False),
        sa.UniqueConstraint(
            "tactical_id", "tactical_linea", "ct_transaction_id", name="uq_tactical_linea_facturas_linea_ct"
        ),
        sa.CheckConstraint("tactical_linea >= 1", name="ck_tactical_linea_facturas_linea"),
    )
    op.execute(BACKFILL_SQL)
    for statement in TRIGGERS_UP:
        op.execute(statement)
    _restaurar_lock_timeout()


def downgrade() -> None:
    _lock_timeout()
    for statement in TRIGGERS_DOWN:
        op.execute(statement)
    op.drop_table(ELEGIDAS)
    op.drop_table(LINEAS_CT)
    _restaurar_lock_timeout()
