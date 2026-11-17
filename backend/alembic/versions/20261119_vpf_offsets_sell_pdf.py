"""offsets and sell in / sell out read ventas por fuera only from the PDF operations (VPF T4)

Revision ID: 20261119_vpf_offsets_sell_pdf
Revises: 20261119_promo_price_recompute_queue
Create Date: 2026-11-16

Owner (S18): "sell in / sell out van a aplicar sobre las operaciones que vayamos creando ahí, no se usa nada viejo".
Owner on what the GBP sync already produced (L15): "Borrarlos y recalcular desde el PDF". So:

- `ventas_fuera_operacion_lineas.item_id`: the product of the line's code (`productos_erp.codigo`), backfilled for
  the lines already loaded; NULL "sin producto";
- the GBP sync (`ventas_fuera_ml_metricas`) stops feeding the queues: its `sell_dirty` and sell out triggers are
  dropped;
- purge: every consumption computed from it is deleted (`sell_in_consumos`, `sell_in_bono_consumos`,
  `sell_out_consumos` and `sell_dirty` with canal `fuera`; `offset_grupo_consumo` / `offset_individual_consumo`
  with `tipo_venta = 'fuera_ml'`). ML and TN rows are not touched;
- canal `fuera` now means the PDF lines (`venta_ref` = `ventas_fuera_operacion_lineas.id`, orchestrator L20); the
  purge above leaves no GBP `it_transaction` under it, so the two key spaces never mix;
- `sell_dirty` row triggers on the PDF lines (and on a document whose client or date changes), frozen copies of
  `app.services.sell.queue`;
- requeue: every PDF line with a product, one remaining sale line of each product that lost consumptions, or of a
  combo containing it (its FIFO gives the freed units to other sales) and every campaign that lost rows (`sell_out_dirty`). The drains rebuild
  them from the PDF lines.

Group offsets keep a summary per group and are recomputed on request, from the PDF lines with `tipo_venta =
'fuera_pdf'`: after deploy run `app.scripts.recalcular_consumo_grupos` (PR body).

Every statement is idempotent: re-running the upgrade leaves the same rows and the same queue (once the drains ran,
it deletes the `fuera` consumptions they rebuilt from the PDF and queues them again). They all run in the migration's
single transaction, so a failure leaves everything as it was. Downgrade drops the PDF triggers, deletes the `fuera` rows of
the queue and of the consumptions and the `fuera_pdf` offset consumptions (computed from the PDF lines by then), restores the GBP triggers and drops
`item_id`; the purged GBP consumptions are not restored (the sell in / sell out backfills rebuild them).
"""

from typing import List, Sequence, Union

from alembic import op

revision: str = "20261119_vpf_offsets_sell_pdf"
down_revision: Union[str, None] = "20261119_promo_price_recompute_queue"
branch_labels: Union[str, Sequence[str], None] = None
depends_on: Union[str, Sequence[str], None] = None

_UPSERT = (
    "ON CONFLICT (canal, venta_ref) DO UPDATE "
    "SET item_id = EXCLUDED.item_id, enqueued_at = now(), attempts = 0, last_error = NULL"
)

UPGRADE_SQL: List[str] = [
    "ALTER TABLE ventas_fuera_operacion_lineas ADD COLUMN IF NOT EXISTS item_id INTEGER",
    "CREATE INDEX IF NOT EXISTS ix_ventas_fuera_operacion_lineas_item_id ON ventas_fuera_operacion_lineas (item_id)",
    """
UPDATE ventas_fuera_operacion_lineas AS l SET item_id = p.item_id
FROM productos_erp AS p
WHERE p.codigo = l.codigo AND l.item_id IS DISTINCT FROM p.item_id
""",
    # The GBP sync is not a sale source any more (S18).
    "DROP TRIGGER IF EXISTS trg_sell_dirty_fuera_insert_delete ON ventas_fuera_ml_metricas",
    "DROP TRIGGER IF EXISTS trg_sell_dirty_fuera_update ON ventas_fuera_ml_metricas",
    "DROP TRIGGER IF EXISTS trg_sell_out_fuera_update ON ventas_fuera_ml_metricas",
    # What the purge touches, read before deleting it.
    """
CREATE TEMP TABLE vpf_t4_productos ON COMMIT DROP AS
SELECT item_id FROM sell_in_consumos WHERE canal = 'fuera'
UNION SELECT item_id FROM sell_in_bono_consumos WHERE canal = 'fuera'
""",
    """
CREATE TEMP TABLE vpf_t4_campanas ON COMMIT DROP AS
SELECT DISTINCT campana_id FROM sell_out_consumos WHERE canal = 'fuera'
""",
    "DELETE FROM sell_in_consumos WHERE canal = 'fuera'",
    "DELETE FROM sell_in_bono_consumos WHERE canal = 'fuera'",
    "DELETE FROM sell_out_consumos WHERE canal = 'fuera'",
    "DELETE FROM sell_dirty WHERE canal = 'fuera'",
    "DELETE FROM offset_grupo_consumo WHERE tipo_venta = 'fuera_ml'",
    "DELETE FROM offset_individual_consumo WHERE tipo_venta = 'fuera_ml'",
    """
CREATE OR REPLACE FUNCTION sell_dirty_enqueue_pdf_linea() RETURNS TRIGGER AS $trg$
DECLARE
    fila ventas_fuera_operacion_lineas%ROWTYPE;
BEGIN
    IF TG_OP = 'DELETE' OR NEW.item_id IS NULL THEN
        fila := OLD;
    ELSE
        fila := NEW;
    END IF;
    IF fila.item_id IS NULL THEN
        RETURN NULL;
    END IF;
    INSERT INTO sell_dirty (canal, venta_ref, item_id) VALUES ('fuera', fila.id, fila.item_id)
    ON CONFLICT (canal, venta_ref) DO UPDATE
    SET item_id = EXCLUDED.item_id, enqueued_at = now(), attempts = 0, last_error = NULL;
    PERFORM pg_notify('sell_dirty', '');
    RETURN NULL;
END;
$trg$ LANGUAGE plpgsql
""",
    "DROP TRIGGER IF EXISTS trg_sell_dirty_pdf_insert_delete ON ventas_fuera_operacion_lineas",
    """
CREATE TRIGGER trg_sell_dirty_pdf_insert_delete
AFTER INSERT OR DELETE ON ventas_fuera_operacion_lineas
FOR EACH ROW EXECUTE FUNCTION sell_dirty_enqueue_pdf_linea()
""",
    "DROP TRIGGER IF EXISTS trg_sell_dirty_pdf_update ON ventas_fuera_operacion_lineas",
    """
CREATE TRIGGER trg_sell_dirty_pdf_update
AFTER UPDATE OF item_id, cantidad, precio, precio_costo, operacion_id ON ventas_fuera_operacion_lineas
FOR EACH ROW WHEN (
    (OLD.item_id, OLD.cantidad, OLD.precio, OLD.precio_costo, OLD.operacion_id)
    IS DISTINCT FROM (NEW.item_id, NEW.cantidad, NEW.precio, NEW.precio_costo, NEW.operacion_id)
)
EXECUTE FUNCTION sell_dirty_enqueue_pdf_linea()
""",
    """
CREATE OR REPLACE FUNCTION sell_dirty_enqueue_pdf_operacion() RETURNS TRIGGER AS $trg$
BEGIN
    INSERT INTO sell_dirty (canal, venta_ref, item_id)
    SELECT 'fuera', l.id, l.item_id FROM ventas_fuera_operacion_lineas AS l
    WHERE l.operacion_id = NEW.id AND l.item_id IS NOT NULL
    ORDER BY l.id
    ON CONFLICT (canal, venta_ref) DO UPDATE
    SET item_id = EXCLUDED.item_id, enqueued_at = now(), attempts = 0, last_error = NULL;
    IF FOUND THEN
        PERFORM pg_notify('sell_dirty', '');
    END IF;
    RETURN NULL;
END;
$trg$ LANGUAGE plpgsql
""",
    "DROP TRIGGER IF EXISTS trg_sell_dirty_pdf_operacion_update ON ventas_fuera_operaciones",
    """
CREATE TRIGGER trg_sell_dirty_pdf_operacion_update
AFTER UPDATE OF empresa, cliente, cliente_codigo, fecha ON ventas_fuera_operaciones
FOR EACH ROW WHEN (
    (OLD.empresa, OLD.cliente, OLD.cliente_codigo, OLD.fecha)
    IS DISTINCT FROM (NEW.empresa, NEW.cliente, NEW.cliente_codigo, NEW.fecha)
)
EXECUTE FUNCTION sell_dirty_enqueue_pdf_operacion()
""",
    # Requeue: the PDF lines (new sales), then one remaining line of each product that lost consumptions.
    f"""
INSERT INTO sell_dirty (canal, venta_ref, item_id)
SELECT 'fuera', id, item_id FROM ventas_fuera_operacion_lineas WHERE item_id IS NOT NULL ORDER BY id
{_UPSERT}
""",
    f"""
INSERT INTO sell_dirty (canal, venta_ref, item_id)
SELECT v.canal, v.ref, v.item
FROM vpf_t4_productos AS p
CROSS JOIN LATERAL (
    -- the product itself or a combo containing it: a component sold only inside combos still gets its FIFO rerun
    SELECT ARRAY[p.item_id] || ARRAY(
        SELECT c.combo_item_id FROM combo_componentes AS c WHERE c.componente_item_id = p.item_id
    ) AS items
) AS k
CROSS JOIN LATERAL (
    SELECT u.canal, u.ref, u.item FROM (
        (SELECT 1 AS orden, 'fuera'::text AS canal, l.id::bigint AS ref, l.item_id AS item
         FROM ventas_fuera_operacion_lineas AS l WHERE l.item_id = ANY(k.items) ORDER BY l.id LIMIT 1)
        UNION ALL
        (SELECT 2, 'ml', s.item_row_id, s.product FROM ml_sale_lines AS s WHERE s.product = ANY(k.items)
         ORDER BY s.item_row_id LIMIT 1)
        UNION ALL
        (SELECT 3, 'tn', t.it_transaction, t.item_id FROM ventas_tienda_nube_metricas AS t
         WHERE t.item_id = ANY(k.items) AND t.it_transaction IS NOT NULL ORDER BY t.it_transaction LIMIT 1)
    ) AS u ORDER BY u.orden LIMIT 1
) AS v
ORDER BY v.canal, v.ref
{_UPSERT}
""",
    """
INSERT INTO sell_out_dirty (campana_id)
SELECT campana_id FROM vpf_t4_campanas ORDER BY campana_id
ON CONFLICT (campana_id) DO UPDATE SET enqueued_at = now(), attempts = 0, last_error = NULL
""",
    "SELECT pg_notify('sell_dirty', '')",
    "SELECT pg_notify('sell_out_dirty', '')",
]

DOWNGRADE_SQL: List[str] = [
    "DROP TRIGGER IF EXISTS trg_sell_dirty_pdf_operacion_update ON ventas_fuera_operaciones",
    "DROP FUNCTION IF EXISTS sell_dirty_enqueue_pdf_operacion()",
    "DROP TRIGGER IF EXISTS trg_sell_dirty_pdf_update ON ventas_fuera_operacion_lineas",
    "DROP TRIGGER IF EXISTS trg_sell_dirty_pdf_insert_delete ON ventas_fuera_operacion_lineas",
    "DROP FUNCTION IF EXISTS sell_dirty_enqueue_pdf_linea()",
    "DELETE FROM sell_in_consumos WHERE canal = 'fuera'",
    "DELETE FROM sell_in_bono_consumos WHERE canal = 'fuera'",
    "DELETE FROM sell_out_consumos WHERE canal = 'fuera'",
    "DELETE FROM sell_dirty WHERE canal = 'fuera'",
    "DELETE FROM offset_grupo_consumo WHERE tipo_venta = 'fuera_pdf'",
    "DELETE FROM offset_individual_consumo WHERE tipo_venta = 'fuera_pdf'",
    # Frozen copies of the GBP triggers as main had them before this revision.
    "DROP TRIGGER IF EXISTS trg_sell_dirty_fuera_insert_delete ON ventas_fuera_ml_metricas",
    """
CREATE TRIGGER trg_sell_dirty_fuera_insert_delete
AFTER INSERT OR DELETE ON ventas_fuera_ml_metricas
FOR EACH ROW EXECUTE FUNCTION sell_dirty_enqueue_venta('fuera')
""",
    "DROP TRIGGER IF EXISTS trg_sell_dirty_fuera_update ON ventas_fuera_ml_metricas",
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
    "DROP TRIGGER IF EXISTS trg_sell_out_fuera_update ON ventas_fuera_ml_metricas",
    """
CREATE TRIGGER trg_sell_out_fuera_update
AFTER UPDATE ON ventas_fuera_ml_metricas
REFERENCING OLD TABLE AS viejas NEW TABLE AS nuevas
FOR EACH STATEMENT EXECUTE FUNCTION sell_out_enqueue_ventas('fuera')
""",
    "DROP INDEX IF EXISTS ix_ventas_fuera_operacion_lineas_item_id",
    "ALTER TABLE ventas_fuera_operacion_lineas DROP COLUMN IF EXISTS item_id",
]


def upgrade() -> None:
    for sql in UPGRADE_SQL:
        op.execute(sql)


def downgrade() -> None:
    for sql in DOWNGRADE_SQL:
        op.execute(sql)
